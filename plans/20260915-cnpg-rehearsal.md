# CNPG backup and recovery rehearsal

## Overview

A disposable SQL application exercises Apollo's Postgres component before household databases move.
The application creates known records, changes them after a base backup, and checks the recovered data
before making fresh writes. The rehearsal uses `cnpg-smoke` in the existing `database` namespace.

This supersedes the declined rehearsal in [the database split plan](11-cnpg-database-split.md).
Mealie still proves recovery from the old cluster's in-tree Barman archive; this rehearsal proves the
Apollo plugin's own backup and recovery path.

## Design

The database uses the shared Postgres component and its initialization component, a single instance,
and a dedicated `cnpg-smoke/` prefix in Apollo's CNPG bucket. The PostgreSQL image matches the component
fixture. SQL Jobs connect through the generated application credentials, with no superuser access,
ingress, or application PVC. Each Job has its own Flux Kustomization and runs once with a fixed name.
Completed Jobs stay available for inspection; there is no TTL that would cause Flux to rerun them.

The disposable Cluster explicitly enables Flux pruning. The shared component remains protected.
Deletion and recreation are separate merged revisions, with an absence check between them. This
exercises the default recovery path with the original archive identity and newly provisioned storage.
The database Kustomization, ObjectStore, and backup ExternalSecret survive the gap.

Scheduled backups stay suspended from the seed stage through teardown. A named base backup follows the seed Job;
a later Job inserts, updates, and deletes records. Recovering those later changes proves WAL replay.
The test sets `archive_timeout` to one minute and uses serial WAL archiving so the workload can wait
for the WAL segment containing its committed changes to appear in `pg_stat_archiver`. This is a bounded
wait with a failure exit, not a fixed delay treated as success.

Removing the init component after the seed backup exercises the documented transition of a running
database to recovery configuration. PR3 verifies that the owning Kustomization accepts this change
before the database is deleted; deferring it until recreation would omit that lifecycle check.

The restore Job checks all expected records before writing anything. It cannot initialize an empty
database or repair missing rows. It then performs another transaction and checks the new state.
It connects using the recreated application Secret, proving CNPG reconciles those credentials with
the restored database owner. An authentication failure blocks this gate before data checks begin.
A second named backup proves the restored database can still back up.

## PR stack and merge gates

Merge one PR at a time. Wait for Flux to observe that merge and pass its live gate before merging the
next PR. Never merge the entire stack together: Flux could skip the intermediate states. Draft PRs
and passing CI establish only that the changes render, not that backup and recovery have succeeded.

| PR | Change | Gate before the next merge |
|---|---|---|
| 1: Initialize | Register the disposable database with explicit init and pruning enabled. | Database Ready, credentials synchronized, initial scheduled backup completed. |
| 2: Seed and back up | Suspend the schedule; seed 1,000 deterministic rows; take `cnpg-smoke-seed` after the Job completes. | Seed Job Complete, named Backup completed, no other backup running. |
| 2a: Retry seed | Preserve SQL ConfigMaps during Flux substitution; replace the failed seed Job with `cnpg-smoke-seed-v2`. | Retry Job Complete and `cnpg-smoke-seed` Backup completed before PR3. |
| 3: Exercise WAL | Remove the init reference; run the post-backup insert/update/delete workload and wait for its WAL to archive. | Database Kustomization Ready with PR3's revision and recovery bootstrap applied; WAL Job Complete; record its counts and WAL filename; schedule remains suspended. |
| 4: Remove database | Prune the SQL Jobs, named Backup, Cluster, and ScheduledBackup while retaining the archive configuration and credentials. | Old Cluster, pods, and PVCs absent; old Longhorn volumes detached/deleted; no writer remains. |
| 5: Restore and write | Recreate the Cluster using the base component's default recovery; validate both datasets, then make and check new writes. | New Cluster/PVC UIDs; restore logs show Barman recovery; verifier authenticates using the recreated application Secret, validates recovered data, and completes. |
| 6: Back up restored database | Keep scheduling suspended and take `cnpg-smoke-restored` after verification. | Named Backup completed; WAL archiving healthy on the restored database; schedule remains suspended. |
| 7: Retire database | Prune the verifier, backup, Cluster, and ScheduledBackup; retain the ObjectStore and credentials until shutdown finishes. | Cluster, pods, and PVCs absent; no remaining Longhorn volume for the test. |
| 8: Remove scaffolding | Remove the remaining Flux owner, ObjectStore, ExternalSecret, and test directory. | Test resources absent; record the observed results in `docs/databases.md`. |

The final cleanup removes Kubernetes resources only. R2 objects remain until the operator removes
the test prefix. Retention is enforced by the running backup machinery and must not be assumed to
clean up an archive after its database is gone. Confirm the prefix is empty before repeating init;
otherwise use a new application/archive identity throughout a new rehearsal.

## Preconditions

- `plugin-barman-cloud`, `longhorn-config`, and `onepassword-store` are Ready.
- The operator confirms the `cloudflare-r2` and `cnpg-r2` items described in
  [Apollo databases](../docs/databases.md) are present and the CNPG credential can read/write its bucket.
  Agents do not inspect the values.
- The operator confirms `s3://tf-hcc-apollo-cnpg/cnpg-smoke/` is unused.
- Apollo has capacity for the component's database and sidecar requests and a 5 GiB Longhorn volume.

## Verification

Every stage runs `task kubernetes:kubeconform CLUSTER=apollo` and renders Apollo's Flux Kustomizations.
The existing Postgres component tests cover the common initialization and recovery manifests.

Read-only inspection commands use the explicit `apollo` context:

```sh
kubectl --context apollo -n flux-system get kustomizations
kubectl --context apollo -n database get cluster cnpg-smoke-pg
kubectl --context apollo -n database get scheduledbackup cnpg-smoke-pg
kubectl --context apollo -n database get backups.postgresql.cnpg.io
kubectl --context apollo -n database get jobs -l app.kubernetes.io/name=cnpg-smoke
kubectl --context apollo -n database logs job/cnpg-smoke-seed-v2
kubectl --context apollo -n database logs job/cnpg-smoke-wal
kubectl --context apollo -n database logs job/cnpg-smoke-verify
kubectl --context apollo -n database get pods,pvc -l cnpg.io/cluster=cnpg-smoke-pg
```

Read each owning Kustomization's `status.lastAppliedRevision` as well as its Ready condition. Record the
initial Cluster and PVC UIDs before deletion, and compare them with the restored objects. Record the
named Backup's `status.backupId`, phase, and completion time; do not confuse the empty initialization
backup with the backup taken after the seed Job. Inspect restore/bootstrap pod logs before they are
removed, and preserve only non-sensitive evidence in the run record.

After PRs 4 and 7, also inspect Longhorn volumes for the recorded PVCs. A missing Kubernetes object
alone does not establish that storage cleanup completed. If resources remain, stop the sequence and
investigate. Any live mutating command requires separate operator approval under `AGENTS.md`.

## Failure handling and security

Keep the current stage when a gate fails. Repair its manifests in a follow-up commit and repeat that
gate. Failed Jobs use `backoffLimit: 0`; an intentional retry needs a new Job name in git after diagnosis.
Do not revert to initialization after a backup exists, and never start a second writer against this
archive. During the recovery gap, keep the ObjectStore, ExternalSecret, and R2 archive intact.

SQL Jobs run as UID/GID 568 with a read-only root filesystem, no Linux capabilities, and no service
account token. They read only their generated application username/password from Kubernetes Secret
references. Their logs contain synthetic data checks and WAL filenames, never connection credentials.
The database retains the upstream image's required UID/GID through the shared component.

This run covers initialization, application authentication, base backup, WAL replay, fresh-storage
recovery, restored writes, backup after recovery, and teardown. Point-in-time targets, multi-instance
failover, and migration from the old archive remain separate tests.

## References

- [Postgres component and recovery lifecycle](../docs/databases.md)
- [Barman plugin: declarative backups and recovery](https://cloudnative-pg.io/plugin-barman-cloud/docs/usage/)
- [PostgreSQL WAL inspection functions](https://www.postgresql.org/docs/18/functions-admin.html)

## Run record

Initialization passed: credentials synchronized, database and Flux owner Ready, continuous archiving healthy,
and scheduled backup `20260915T213601` completed on 2026-09-15 at 21:36:08 UTC.
Initial Cluster UID: `248f8c88-3be3-4de0-a49e-2f5ceceb448a`.
Initial PVC UID: `e5e05ac0-bcde-4fa6-9e86-11a75dcf9b2a`.

The first seed Job failed because Flux substitution reduced SQL dollar-quote delimiters from `$$` to `$`.
Its transaction rolled back and the dependent named backup did not start. PR2a retries the seed with
substitution disabled on its SQL ConfigMap. Later SQL stages use the same protection.

Attach the remaining backup IDs, Job results, and restored resource UIDs during execution.
After cleanup, move the durable outcome to `docs/databases.md` and replace this plan with a pointer.
