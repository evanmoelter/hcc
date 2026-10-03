# Paperless migration

Preparation and cutover record for Paperless and scanner SFTP, following Authentik in the
[Talos migration](../20260816-talos-migration.md). The operator confirmed Authentik's data, login,
Mealie OIDC, WebFinger/Tailscale, SMTP, and proxy-header checks passed on 2026-09-30.
Paperless is running on Apollo; the operator confirmed data access and a successful scanned document.
Archived with the cleanup PR at the operator's request. Unchecked items retain outstanding backup,
cleanup, credential-retirement, or verification work; archival does not mark them complete.

## Decisions and prepared stack

- Move the old Paperless 2.19.6 instance to Apollo on 2.20.15. Complete and verify that migration
  before a separate 3.x upgrade. The [v3 migration prerequisites](https://github.com/paperless-ngx/paperless-ngx/blob/v3.2.1/docs/migration-v3.md#pre-requisites)
  require upgrading from 2.20.15; review duplicate handling and API clients with the operator then.
- Keep `paperless.${SECRET_DOMAIN}` on LAN and the `paperless` Tailscale hostname. No public
  Paperless route is introduced. Keep the existing Authentik provider and local recovery login.
- Keep Brother scanner SFTP, moving its load-balancer address to `192.168.21.102`. The scanner is
  on the IoT VLAN; the operator must allow its specific source address to that destination on TCP 22.
- Restore the library into 50 GiB and import only the `paperless` database into a dedicated Apollo
  PostgreSQL 18 cluster. Create an empty 1 GiB RWX consume claim and a fresh memory-only Dragonfly
  instance after draining source ingestion and jobs.

The operator approved this two-PR Graphite stack, to be reviewed and merged in cutover order:

1. **[Disable on main, PR #315](https://github.com/evanmoelter/hcc/pull/315):** stop Paperless and SFTP, remove the SFTP load-balancer Service and old
   internal and Tailscale Ingresses. Retain their configuration in git, both PVCs, source database,
   encrypted Secrets, HelmReleases, and VolSync configuration for final backup and rollback.
2. **[Rebuild on Apollo, PR #317](https://github.com/evanmoelter/hcc/pull/317):** add separate restore-preflight, storage, database, broker, app, SFTP, and
   backup lifecycles. The library backup Kustomization starts suspended pending data verification.

Do not merge the stack together. This document does not authorize live changes. Merges, on-demand
backups, suspensions, firewall changes, and DNS ownership repairs require operator action or explicit
approval. Read-only checks below do not perform a cutover.

## Before the maintenance window

Both PRs must pass review and the applicable [repository validation](../../AGENTS.md#validating-changes).
Inspect the old-cluster rendered diff to ensure the disable retains data and the shared database and
Dragonfly services. Keep the source app release available for rollback.

The operator supplies these items in `hcc-apollo`; agents do not inspect or copy their values:

| Item | Fields and purpose |
|---|---|
| `paperless` | Original `PAPERLESS_SECRET_KEY` and unchanged `PAPERLESS_SOCIALACCOUNT_PROVIDERS` JSON |
| `paperless-postgres-migration` | Original `PAPERLESS_DBPASS` for source role `paperless-db` |
| `paperless-sftp` | Original `SFTP_USERS`, `SSH_KEY_ED25519`, and `SSH_KEY_RSA` |
| `paperless-dragonfly` | New `password` used by both the broker and Paperless |
| `paperless-library-migration` | Original `RESTIC_PASSWORD`; `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` scoped to the old VolSync bucket, with Object Read & Write for restic locks |
| `paperless-library` | New `RESTIC_PASSWORD` for Apollo's independent library repository |
| `cloudflare-r2` | Existing shared `ACCOUNT_ID`, used to construct the R2 endpoint |
| `volsync-r2`, `cnpg-r2` | Existing credentials scoped to their separate Apollo backup buckets |

Preserve the application secret key, provider JSON, scanner account, and both SSH host keys exactly.
The provider JSON contains configuration and credentials together; retaining this bundle is a temporary
migration exception to keeping non-secret settings in git. Its provider ID is not yet independently
established, and rewriting it could change callback paths or account identity. Extract readable
configuration only after the operator verifies that identity. Never print the JSON or secret values.
Confirm `SFTP_USERS` still defines the `paperless-sftp` account with UID/GID 1000 and its existing
password format; changing the account name would also require changing the mounted home path.

The configured restore source is `tf-hcc-volsync/paperless-library`. The actual repository URL is
inside the old encrypted Secret and has not been read. **The operator must verify its bucket and
suffix before merging Apollo**, then correct `VOLSYNC_RESTORE_BUCKET`/`VOLSYNC_RESTORE_PATH` through
git if they differ. Preflight confirms a restic snapshot exists; it does not prove this is the correct
app repository. Confirm the selected source uses the shared R2 account and original restic password.

Confirm Apollo's destination paths are unused: `tf-hcc-apollo-volsync/paperless-library` and
`tf-hcc-apollo-cnpg/paperless/`, with Barman server name `paperless-pg-apollo-v1`. A prior attempt needs
diagnosis and an explicit recovery decision. Never reuse a partial restore ID or an unrelated archive.

Read-only preparation found 247 documents, a roughly 21 MB PostgreSQL 16.2 database owned by
`paperless-db`, and only the `plpgsql` extension. The library held 258,225,842 bytes and the consume
directory was empty. Refresh these measurements after draining ingestion and record representative
document counts, original/archive checksums, tags, users, permissions, and workflows privately for
comparison. Do not put document contents, account details, or credentials in git.

Recheck free Longhorn capacity on all three storage nodes. The 50 GiB library restore temporarily
needs both the restored source volume and the permanent claim, each replicated; include cache,
consume, and database allocations. Keep the temporary restore volume until verified cleanup because
Longhorn needs it while cloning the snapshot. Recent successful source backups and healthy capacity
observed during preparation do not replace the final cutover checks.

Verify the temporary Apollo-to-`192.168.6.21:5432` firewall path in
[networking.md](../../docs/networking.md). Import uses TLS with `sslmode: require`; it does not verify the
IP endpoint's certificate identity. The destination app uses CNPG-generated credentials and verifies
the Apollo database service certificate. Confirm the source role can read all Paperless objects and
take a logical dump; do not substitute a superuser password merely to bypass an unexplained failure.

Identify the scanner's actual source address and prepare the narrow IoT firewall allowance to
`192.168.21.102:22`; do not allow the entire IoT VLAN into Apollo. If its destination is a literal old
IP, change that scanner setting during the maintenance window. If it uses `paperless-sftp.${SECRET_DOMAIN}`,
verify IoT DNS resolves the new address. Preserve its SSH host-key fingerprints and remote directory.

## Cutover gates

### 1. Drain ingestion, stop source writers, and take final backups

Pause scanning, UI/API uploads, mail ingestion, and other producers first. Let Paperless finish
active, reserved, and queued work, then confirm there are no unprocessed files in consume or pending
jobs. A fresh Apollo broker will not inherit source queue contents. If something cannot drain, stop
and resolve it before proceeding; an empty directory observed earlier is insufficient.

Merge only the disable PR. Wait for `main` Flux to apply it and verify both Deployments have zero
running pods. Check that no producer or late job wrote after the drain. If ingestion raced the stop,
hold the migration and arrange another controlled drain on the old app rather than discarding files.

```sh
kubectl --context main -n default get deployments paperless paperless-sftp
kubectl --context main -n default get pods,ingresses,services,endpointslices
kubectl --context main -n default get pvc paperless-library paperless-consume
kubectl --context main -n database get cluster cnpg-cluster
kubectl --context main -n default get replicationsource paperless-library-r2
```

The old SFTP Service must be gone, releasing its address and DNS ownership. Wait for the old Tailscale
proxy and hostname to be released if present. Both old Paperless Ingresses must be gone.
Verify actual DNS ownership before Apollo claims the names; do not assume workload shutdown removes
records or tailnet devices immediately.

Query main's `k8s-gateway` at `192.168.6.15` explicitly and verify it no longer returns the old
ingress address `192.168.6.10` after the Ingress disappears and cached answers expire. Record that
answer alongside the answers from the resolvers actually used by LAN and IoT clients. With
`SECRET_DOMAIN` set locally:

```sh
dig @192.168.6.15 "paperless.${SECRET_DOMAIN}" A +short
dig @192.168.4.1 "paperless.${SECRET_DOMAIN}" A +short
dig "paperless.${SECRET_DOMAIN}" A +short
```

Repeat from each relevant client network using its configured resolver; a workstation's default
lookup alone does not cover the LAN and IoT paths. Investigate any remaining old ingress answer:
compare a nonexistent hostname in the same domain to distinguish a wildcard fallback from a stale
Paperless record. During this cutover, UniFi answered both with `192.168.6.10`, while Mealie's actual
configured hostname resolved to `192.168.21.100`; explicit Apollo records take precedence over the
fallback. Hold for a remaining Paperless-specific old record. A verified wildcard fallback can remain
during the outage, but gate 3 must verify that Apollo's new Paperless record overrides it at the actual
client resolvers before normal use resumes.

With explicit approval, trigger and verify a final VolSync sync of `paperless-library-r2` after the
source writers stopped. Record the manual trigger, completion time, and actual restic snapshot ID.
Also create and verify a final CNPG `Backup` of shared `database/cnpg-cluster` using its existing
`barmanObjectStore` method. That physical backup is a rollback safeguard; Apollo imports the stopped
Paperless database directly and does not restore the other shared databases.

After final sync, suspend the old `paperless` Flux Kustomization and pause its ReplicationSource,
including its recurring trigger, with explicit operator approval. The source belongs to the app's
Kustomization; without suspension Flux could undo the runtime pause. Verify no source mover/pruner
remains active. Keep shared CNPG, its scheduled backups, its operator, and shared Dragonfly running
for any remaining consumers. If either final backup fails, hold Apollo and diagnose or roll back.

### 2. Restore, import, and start Apollo

Merge the Apollo PR only after the previous gate and credential setup. The ordering is restore
preflight → storage → app → library backup; database and broker also gate the app, and SFTP waits
for the app. Library backups remain suspended even after readiness. Keep scanner and other producers
paused throughout data verification; routes become available during this maintenance window.

```sh
kubectl --context apollo -n flux-system get kustomizations
kubectl --context apollo -n default get externalsecrets,jobs,replicationdestinations,pvc
kubectl --context apollo -n default get cluster paperless-pg
kubectl --context apollo -n default get dragonfly paperless-dragonfly
kubectl --context apollo -n default get helmreleases,deployments,httproutes,ingresses,services
kubectl --context apollo -n default logs job/paperless-library-restore-preflight-migration-20260930
kubectl --context apollo -n default logs deployment/paperless
kubectl --context apollo -n default get backups.postgresql.cnpg.io
```

Capture import logs before cleanup and confirm `pg_dump`/`pg_restore` imported only `paperless`.
CNPG's [microservice import](https://cloudnative-pg.io/docs/1.28/database_import/#the-microservice-type)
reassigns ownership to `paperless`; it does not import source roles or their passwords. Confirm the
restic snapshot selected is the final source snapshot and the permanent library references
`paperless-library-bootstrap-migration-20260930`. Both permanent claims must be Bound; successful
preflight or an empty initialized database is not evidence of recovered data.

The app runs as UID/GID 1000 to preserve restored ownership and scanner writes. It retains a read-only
root filesystem and drops capabilities. The writable runtime and export mounts accommodate the
upstream image; runtime installation of extra OCR languages is not configured. SFTP keeps a separate
rootful exception for account setup and OpenSSH chroot, with only its required capabilities and a
writable root filesystem. Host keys come from the original Secret. The upstream
[account-creation script](https://github.com/atmoz/sftp/blob/master/files/create-sftp-user) logs its
user specification, so the entrypoint's stdout is suppressed to prevent credentials entering logs;
sshd diagnostics remain on stderr. Preserve that suppression when changing startup or troubleshooting.

### 3. Verify data, access, scanner ingestion, and backups

Before allowing normal use, compare source and destination document counts and representative
originals, archives, thumbnails, text searches, tags, metadata, users, permissions, and workflows.
Confirm the 2.20.15 database migrations completed and no ownership, database TLS, or broker errors
remain. Never start the old app against the upgraded Apollo database.

- Confirm the internal HTTPRoute reports current-generation Accepted and ResolvedRefs. Repeat the
  gate 1 DNS queries after Apollo's UniFi record appears and cached answers expire. Every resolver
  used by LAN and IoT clients for Paperless must return `192.168.21.100`, with no old ingress address.
  The direct `k8s-gateway` query must also remain free of the old ingress address. Hold the cutover
  if any client still resolves the old ingress. Verify the original
  HTTPS hostname works from those clients and confirm no public route appeared.
- Test fresh Authentik login and logout on LAN and Tailscale, preserving existing account linkage.
  Test from outside the LAN over Tailscale: reaching its HTTPS login page alone is insufficient.
  A canonical-hostname callback must remain reachable from that client. Confirm the provider's
  registered redirect URIs before changing anything, and keep the local recovery login available.
- Confirm SFTP resolves to `192.168.21.102`, the scanner sees its original SSH host-key fingerprint,
  and authentication and chroot paths are unchanged. Test denial from unauthorized source networks.
- Resume the scanner for one operator-selected disposable document. Verify its `consume/receipt`
  upload, polling, OCR, receipt tag, barcode behavior, archive, and thumbnail, then test download and
  export. Confirm the consume directory drains and queued jobs finish before resuming normal input.
- Check Dragonfly availability and its Prometheus target. Its replication is not durable job backup;
  unresolved ingestion failures must be diagnosed rather than treated as migration success.

Remove `spec.suspend: true` from `paperless-library-backup` through git after data and application
checks pass. Wait for an actual snapshot in Apollo's independent restic repository, not only a mover
success. Verify the first Apollo CNPG backup and continuous WAL archiving. Record backup identifiers
and completion times; keep source data and backups intact through Wave 1.

### 4. Remove temporary migration resources

After data, login, scanner ingestion, and both Apollo backups pass, prepare a cleanup PR:

- Remove restore preflight, the storage restore component and capacity replacement, preflight/VolSync
  dependencies, and destination readiness check. Keep both protected PVCs, PVC readiness, the same
  storage Kustomization, and the library's immutable `dataSourceRef` exactly as bound.
- Remove the database import/externalClusters patches, the empty-archive-check removal, and the
  migration ExternalSecret. The Postgres component then supplies recovery from Apollo's archive.
  Keep the protected Cluster, database Kustomization, archive path, and server identity.
- Update migration tests to assert the verified cleanup state. Run the applicable validation, then
  verify temporary resources are pruned while permanent PVC/PV and database identities remain intact.
- Have the operator revoke the old-bucket migration R2 credentials and archive temporary 1Password
  items. Keep the original restic password and source database password available for rollback.

Retain `postgres-lb` and its temporary firewall path for TeslaMate's later import. Keep old Paperless
manifests and data until Wave 2. This complete plan is archived under `plans/done/` in the cleanup
PR at the operator's request, with pending verification preserved below.

The operator requested one PR for backup enablement and cleanup: [PR #321](https://github.com/evanmoelter/hcc/pull/321)
removes the backup suspension as well as temporary migration resources. **Do not merge until the
first actual Apollo library snapshot is recorded.** To verify that prerequisite before this combined
PR merges, obtain explicit approval to resume the existing live backup Kustomization temporarily,
wait for its ReplicationSource and credentials, and trigger a manual backup. Verify the snapshot ID,
then clear the manual trigger so the configured schedule can run. Parent Flux reconciliation may
restore the suspension before merge; the PR makes backup enablement permanent. This is a proposed
one-time exception to enabling backups through git, not authorization to perform it.

The PR removes no source-cluster resources and does not revoke credentials. After merge, verify
pruning and permanent resource identities before retiring the two migration items. The archived
record preserves those outstanding checks.

## Rollback

Pause producers again. Through git, disable Apollo's internal route and Tailscale Ingress, stop
Paperless and SFTP, remove the SFTP Service, and suspend Apollo library backups. Confirm pods and
endpoints are gone before restoring the source. Preserve Apollo's database and PVCs for diagnosis;
their deletion needs an explicit decision.

Check LAN DNS and tailnet ownership. UniFi external-dns uses `sync`, so verify it removes the affected
Apollo LAN records after the route and SFTP Service disappear. Cloudflare's `upsert-only` policy does
not govern these LAN-only resources. If stale records remain, the operator must remove or hand off only
the affected Apollo-owned records after checking ownership. Release the Tailscale hostname before the old proxy claims it.
Restore the scanner's old IP if configured literally and remove the temporary IoT allowance when unused.

Revert the entire old-disable PR through git, restoring both Ingresses as well as the workloads
and SFTP Service. Resume the old `paperless`
Kustomization and VolSync writer only with operator approval, then verify old app, SFTP, routes, DNS,
and ingestion before releasing the scanner. The source remains on its original database schema;
rolling back by pointing the old image at Apollo's upgraded database is unsupported. Writes accepted
on Apollo after import do not exist on the source: agree to their loss or a separate transfer before
rollback. Never restore the shared physical backup over other apps' newer databases.

## Preparation evidence and execution record

The 3.x review identified major consumer, search, document-version, and API changes in the
[release notes](https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.0.0). The selected
2.20.15 migration step leaves those behavior decisions for a separately verified upgrade.
A disposable ARM64 Docker proof exercised the upstream Paperless image as UID/GID 1000 with a
read-only root filesystem, PostgreSQL 18, OCR ingestion, and export. A separate upstream SFTP proof
checked password uploads with the Brother-compatible SSH algorithms. These are preparation evidence,
not an Apollo restore or a physical scanner test.

Local validation passed schema checks for both cluster trees, Apollo policy lint, all 39 component
tests, and the full Apollo Flux/Helm render (115 passed; the intentionally suspended library backup
was skipped and is covered by the component tests). The old Helm render changes only replica counts,
both Paperless Ingresses, and the SFTP Service plus its generated probes. A separate Dragonfly
runtime proof passed authenticated reads/writes and health checks with its configured security context.

[Jory's Paperless configuration](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/self-hosted/paperless/helmrelease.yaml)
provided the per-app CNPG/Dragonfly comparison. The current onedr0p, billimek, szinn, and Mafyuh trees
had no Paperless implementation. [onedr0p's Radarr](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/default/radarr/app/helmrelease.yaml)
and [szinn's FreshRSS](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/apps/self-hosted/freshrss/app/helmrelease.yaml)
provided examples for hardened app-template workloads and disposable cache mounts; Apollo's established
storage and database components take precedence over their cluster-specific conventions.

### Source shutdown and final backups, 2026-10-03 UTC

- PR #315 merged as `c956f6ab45e80f5763326a2ea2be3b9f584ebca0` at 00:12:38 UTC.
  Main Flux applied that revision. Both Paperless Deployments had zero pods, both Ingresses and the
  SFTP LoadBalancer Service were absent, and no old Paperless Tailscale proxy Pods or Services remained.
- The operator confirmed the 1Password setup was complete. They had not explicitly paused and
  drained ingestion before shutdown, but reported no scans for several days. Subsequent checks found
  zero queued or unacknowledged entries in the source broker's database 2. A separately approved
  temporary Pod mounted consume read-only and counted zero files, two directories, zero other entries,
  and zero errors. That Pod was deleted after verification. These are post-shutdown observations,
  not evidence that the original pre-shutdown drain procedure was followed.
- With explicit operator approval, manual VolSync trigger `paperless-final-20261003` completed at
  00:17:58 UTC and saved restic snapshot `0ff04d69` after source shutdown.
- CNPG Backup `database/paperless-final-20261003` used `barmanObjectStore` on shared `cnpg-cluster`.
  It ran from 00:16:21 to 00:18:56 UTC and completed successfully. The cluster remained healthy with
  continuous archiving and last-backup conditions True.
- After both backups completed, the approved commands suspended main's `paperless` Flux Kustomization,
  set `paperless-library-r2.spec.paused: true`, and removed its recurring schedule. Read-only checks
  confirmed those settings and no remaining library mover Job or Pod. The shared database and broker
  remain running.
- Main `k8s-gateway` and Pi-hole no longer answered Paperless. UniFi resolvers `192.168.4.1` and
  `192.168.20.1` still returned the old ingress through the wildcard behavior described in gate 1.
  Apollo's UniFi DNS controller reported records up to date; Mealie's actual route hostname resolved
  to Apollo through both resolvers. Paperless's new explicit answer remains a post-merge gate.

### Apollo rollout and cleanup draft, 2026-10-03 UTC

- PR #317 merged as `566f14e345382a73f792316eb849c9fa4389748a`. All seven active Paperless Flux
  Kustomizations became Ready; the library-backup Kustomization remains intentionally suspended.
  Application, SFTP, database, and both Dragonfly Pods became Ready with zero restarts.
- VolSync restored final snapshot `0ff04d69`; library cloning completed with three healthy replicas.
  Both claims are Bound. The temporary CNPG import Job was observed successful but removed by CNPG
  before its logs could be captured. Read-only source/destination SQL compared 247 documents and
  matching user, tag, correspondent, and document-type counts, plus the aggregate stored document
  checksum digest. This comparison does not replace checking restored file contents.
- Paperless completed its 2.20.15 database migration and connected to its authenticated broker.
  LAN and Tailscale HTTPS returned 200 with valid certificates from the workstation. UniFi resolvers
  `192.168.4.1` and `192.168.20.1` returned `192.168.21.100` for Paperless and `192.168.21.102` for
  scanner SFTP. The SSH listener responded; consume, receipt, and export directories were writable.
- Apollo CNPG Backup `paperless-pg-20261003031337` completed at 03:14:45 UTC; continuous WAL archiving
  is healthy. The first Apollo library snapshot remains outstanding.
- The operator reported that data looked good through internal and Tailscale access and that scanner
  connectivity was updated and tested. After they scanned a document, logs showed one successful
  consume task and no errors, and the operator confirmed the scanned document looked good.
  OCR/search, receipt/barcode behavior, thumbnail, download/export,
  fresh login/logout, and unauthorized-network denial still need explicit verification where not
  covered by those operator checks.
- Preserve these identities when cleanup reconciles:

  | Resource | UID / backing identity |
  |---|---|
  | `default/paperless-library` | PVC UID `d391036d-32b1-49c8-8af3-dc660ed0e1f6`; PV `pvc-854728be-32c2-40a8-9531-513a94375806` |
  | `default/paperless-consume` | PVC UID `61c3ed93-08d8-4cbc-a882-d6bbb32cf006`; PV `pvc-61c3ed93-08d8-4cbc-a882-d6bbb32cf006` |
  | `default/paperless-pg` | Cluster UID `1ebbd944-2704-4477-8e84-83149edf1076`; PostgreSQL system ID `7692274548515123225` |

- [x] Operator confirmed Authentik verification and approved the two-PR preparation, LAN/Tailscale
  access, retained scanner SFTP, and the staged Paperless upgrade.
- [ ] Both PRs reviewed and CI passed; PR links and merged revisions recorded.
- [ ] Operator verified source repository suffix, copied credentials, and configured the scanner firewall path.
- [x] Old workloads stopped and ingress/proxy resources removed; post-shutdown consume and broker checks empty.
- [x] Final source VolSync snapshot and shared CNPG backup verified and recorded; old library writer paused.
- [x] Apollo library restored from the final snapshot; logical import and application migrations verified.
- [ ] Source/destination data compared; LAN and Tailscale OIDC, scanner upload, OCR, and export verified.
- [ ] First Apollo library snapshot and database backup recorded; WAL archiving healthy.
- [ ] Temporary restore/import resources removed; permanent identities and replicas verified.
- [ ] Migration credentials revoked or archived.
- [x] Full plan and execution record moved to `plans/done/` in PR #321 at the operator's request;
  outstanding checks above remain explicit.
