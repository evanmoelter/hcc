# VolSync components

Use separate Flux Kustomizations for each lifecycle. The
[disposable test](../../apps/storage/volsync-test/) is a complete consumer.

| Component | Owning Kustomization |
|---|---|
| `volsync/preflight` | Wait for `onepassword-store`; `wait: true` checks the repository Job and ExternalSecret. |
| `volsync/restore` | Depend on preflight, `volsync`, and `longhorn-config`; wait for the destination and PVC. |
| `volsync/pvc` | Explicit empty-volume initialization for a new app; depend on `longhorn-config`. |
| `volsync/backup` | Depend on the serving app, `volsync`, and `onepassword-store`. |

Attach through `spec.components`, relative to the owning Kustomization's `spec.path`.
The app depends on its restore Kustomization. Keep `dependsOn` and `healthCheckExprs` on the owner:
a component cannot patch the Flux Kustomization that includes it. Copy the destination readiness expression
from the test's `ks-restore.yaml`; PVC readiness alone does not check the requested restore attempt.

Set `APP` on every owner. It identifies one PVC backup stream; use a distinct name/path for each stream.
`CLAIM` can name the actual PVC independently. Set `VOLSYNC_CAPACITY` on the PVC/restore owner.
Workload claims are protected from Flux pruning; the disposable test explicitly removes that protection.

For recovery, set `VOLSYNC_RESTORE_ID` on both preflight and restore owners, and `VOLSYNC_RESTORE_BUCKET`
on preflight. `VOLSYNC_RESTORE_PATH` defaults to `APP`. Recovery uses the latest backup only.
Use a new ID for every new recovery attempt, including after changing the source or credentials, correcting
a failed preflight, or recreating a PVC. The ID gives the Job, restore Secret, and ReplicationDestination
fresh names so old credentials/completion/images cannot satisfy a new attempt.
Do not add Job TTLs: Flux would recreate completed Jobs indefinitely.

The [upstream mover](https://github.com/backube/volsync/blob/v0.16.0/mover-restic/entry.sh) accepts empty
repositories as successful restores. Preflight instead requires an existing snapshot for host `volsync`
and path `/data`, without initializing or locking the repository. Keep the source backup/prune writer
stopped throughout a migration restore; a completed preflight is a one-time check, not a continuing lock.
Verify application data before enabling traffic and Apollo backups.

## Credentials and migration

The operator creates one shared `cloudflare-r2` item in `hcc-apollo` with field `ACCOUNT_ID`.
ESO constructs the private endpoint from that field; bucket names and repository paths stay in git.

Each app's 1Password item contains `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, and `RESTIC_PASSWORD`. By default its title is `APP`; override with
`VOLSYNC_CREDENTIALS_ITEM` for backups or `VOLSYNC_RESTORE_CREDENTIALS_ITEM` for restores.
Repository locations are rendered into ESO-managed Secrets because restic requires them there.

Backups always write to `tf-hcc-apollo-volsync`, with `APP` as the default repository path.
For migration, explicitly select the existing old repository and a separate restore credential item,
including that repository's original restic password. Both buckets use the shared Cloudflare account.
The upstream restore mover writes lock objects,
so its credential needs object write access even though it only restores data. Scope it to the old bucket
and revoke it after verification. The preflight itself needs only read access.

After the first verified Apollo backup, switch future restore configuration to the Apollo repository and
credentials. Changing restore configuration does not update an already-bound PVC; prepare a fresh recovery
ID when a new recovery is needed. Keep recurring backup configuration in its own Kustomization so its
failures do not block the serving app.

## Disposable proof

`volsync-test` seeds two files into `volsync-test-source`, takes one manual snapshot backup, passes preflight,
hydrates `volsync-test-restored`, then verifies checksums, ownership, and private-file permissions using only
the restored claim. The backup has no schedule. Both claims and all mover/cache volumes use Longhorn.

After merge, require all five `volsync-test-*` Flux Kustomizations to be Ready, inspect the verifier Job's
logs, and confirm the destination names a ready CSI snapshot. This proves fixture recovery, not application
consistency. A failed Job needs diagnosis and a new attempt ID; it does not retry forever.

Remove the test's five registrations in a follow-up commit after verification. Flux then prunes its Jobs,
Secrets, replication resources, and disposable PVCs. The operator removes the R2 test repository and its
1Password item separately. For another full test, use a fresh app name and repository path.

The component structure draws from
[onedr0p's historical restic component](https://github.com/onedr0p/home-ops/tree/8b9a2240317d0f23d9effeef085e9a0c651bd5db/kubernetes/components/volsync).
