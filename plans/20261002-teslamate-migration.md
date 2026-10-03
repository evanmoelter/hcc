# TeslaMate and Grafana migration

Preparation and cutover record for the next app pair in the
[Talos migration](20260816-talos-migration.md). Paperless cleanup is separate work.

## Decisions and stack

The operator chose to migrate historical data before repairing recording on Apollo. The source
TeslaMate 1.33.0 is disconnected: Owner API calls return HTTP 403 while token refreshes succeed.
This matches the [upstream failure](https://github.com/teslamate-org/teslamate/discussions/5400)
addressed by 4.0.0 and the refresh-token fix in
[4.0.1](https://github.com/teslamate-org/teslamate/releases/tag/v4.0.1).
OpenStreetMap address lookups also report TLS certificate failures. These are pre-existing failures;
HTTP readiness cannot establish working vehicle collection.

Keep TeslaMate 1.33.0 and Grafana 12.3.1 for the import and historical-data verification. Import into
an updated PostgreSQL 16 image, preserving the source major. TeslaMate 2.0 and later require at least
[PostgreSQL 16.7 or 17.3](https://github.com/teslamate-org/teslamate/releases/tag/v2.0.0).
The destination meets that prerequisite without combining a PostgreSQL major upgrade with this move.
A separate Apollo change upgrades TeslaMate after the import passes verification. PostgreSQL 18 can
follow after the application supports it; it is not required to repair the Owner API connection.

Preserve LAN-only TeslaMate access, LAN and Tailscale Grafana access, Grafana's anonymous Editor role,
and disabled MQTT. The operator confirmed no manually created Grafana dashboards need preservation
and that the 2024 SQL dump is obsolete. Its legacy PVC is absent from the live cluster. Retain its
manifests through Wave 2 anyway. Grafana remains disposable, with dashboards pinned to the imported
TeslaMate release rather than changing with upstream's default branch.

Prepare and review two Graphite PRs:

1. Disable TeslaMate and Grafana on main: zero replicas, disable internal Ingresses, and stop rendering
   Grafana's Tailscale Ingress. Keep releases, secrets, the shared database, and old configuration.
2. Rebuild on Apollo: import TeslaMate into its own CNPG cluster, then start the app and Grafana.
   Grafana reads the dedicated database, and its Tailscale lifecycle waits for the app and operator.

Merge separately in this order. No live mutation is authorized by this runbook. Obtain operator
approval for merges, on-demand backups, database privilege changes, or any other cluster write.

## Operator preparation

Create these items in `hcc-apollo`; agents must not inspect or copy their values:

| Item | Field | Purpose |
|---|---|---|
| `teslamate` | `ENCRYPTION_KEY` | Exact original value, so imported Tesla tokens remain readable |
| `teslamate-postgres` | `password` | New destination application password, also consumed by Grafana |
| `teslamate-postgres-migration` | `password` | Original `DATABASE_PASS` for the source `teslamate` role, used only for logical import |
| `cloudflare-r2`, `cnpg-r2` | Existing fields | Existing Apollo backup account and bucket-scoped credentials |

Inspection of the encrypted files' key names confirmed TeslaMate has `ENCRYPTION_KEY`, `DATABASE_USER`,
`DATABASE_PASS`, `DATABASE_NAME`, `DATABASE_HOST`, and legacy `INIT_POSTGRES_*` fields. Grafana has only
`TESLAMATE_DB_USER` and `TESLAMATE_DB_PASSWORD`. No values were decrypted. Apollo defines its database
host, name, and username in Helm values and supplies a new shared destination password through ESO.
The legacy initialization/restore fields are not needed by Apollo's CNPG import.

Copy `ENCRYPTION_KEY` unchanged. Source database ownership was verified as `teslamate`; the operator
must confirm the encrypted `DATABASE_USER` is that role before copying `DATABASE_PASS`, and verify
that role can dump all objects over `192.168.6.21:5432`.

The database Kustomization depends on `onepassword-store` and includes the credential ExternalSecrets
alongside the Cluster, following Paperless's layout. The destination basic-auth Secret has literal
username `teslamate`. Grafana's namespace receives the same password through its own ExternalSecret.
See [database guidance](../docs/databases.md) and
[secret integration](../docs/secrets.md).

Confirm `tf-hcc-apollo-cnpg/teslamate/` and server name `teslamate-pg-apollo-v1` are unused. Keep the
source archive independent. Check three-node Longhorn capacity for a new 20 GiB volume with three
replicas, allowing room for existing workloads and rebuilds. Verify the temporary Apollo-to-main
PostgreSQL path in [networking](../docs/networking.md).

The source database reports healthy WAL archiving and a recent successful backup. This is not a
restore rehearsal or a substitute for the final backup. Record a private baseline of row counts,
latest historical timestamps, representative drives/charges, vehicles, settings, geofences, and
schema migration versions. Exclude tokens and location data from logs, commits, and PRs.

## Cutover

### Stop the old writers and release names

Merge only the disable PR. Wait for Flux and confirm both deployments have zero pods. Despite the
API outage, TeslaMate still writes settings, state, and background repair results; it must stop before
import. Stop other clients that can write its database. The shared CNPG cluster remains running.

```sh
kubectl --context main -n flux-system get kustomizations teslamate grafana
kubectl --context main -n default get deployment teslamate
kubectl --context main -n monitoring get deployment grafana
kubectl --context main -n default get pods,ingresses
kubectl --context main -n monitoring get pods,ingresses
kubectl --context main -n database get cluster cnpg-cluster
```

Confirm both internal Ingresses and Grafana's Tailscale Ingress and proxy have disappeared. Check
main's k8s-gateway at `192.168.6.15`, UniFi at `192.168.4.1`, and the actual client resolver. Main's
k8s-gateway must stop publishing both names. If UniFi still answers `192.168.6.10`, compare a nonexistent
hostname to distinguish its wildcard fallback from an app-specific record, as in the
[Paperless cutover](done/20260930-paperless-migration.md). A verified wildcard fallback can remain
during the outage; verify Apollo's explicit records override it at the client resolvers after deployment.
Hold for any remaining app-specific old record. Confirm the old tailnet `grafana` device/name is released
as well.

Refresh the private data baseline after shutdown. With explicit approval, take an on-demand CNPG
backup of `cnpg-cluster`, wait for completion, and record its backup ID and final archived WAL.
Keep the shared archive and scheduled backup running for the remaining old-cluster services;
there is no TeslaMate VolSync writer to suspend.

### Import and verify history on Apollo

Merge the Apollo PR only after the final backup and name-release gates pass. Flux applies the
credential ExternalSecrets and database together, then waits for database readiness before starting
the app and Grafana. CNPG imports only
`teslamate`, not the other databases in the source cluster.

```sh
kubectl --context apollo -n flux-system get kustomizations teslamate-database teslamate grafana grafana-tailscale
kubectl --context apollo -n default get cluster teslamate-pg
kubectl --context apollo -n default get pods
kubectl --context apollo -n monitoring get pods,httproutes,ingresses
```

CNPG microservice import temporarily elevates the destination owner while restoring and removes
that privilege afterward. It restores extensions with application ownership. Do not add duplicate
`CREATE EXTENSION` initialization hooks. Verify `cube` and `earthdistance` are present, the database
and tables belong to `teslamate`, and the application role is not a superuser. The restored extension
version may use the destination image's newer default; record the actual versions.

Compare table counts and representative historical data against the final source baseline before
accepting the import. Confirm historical Grafana panels, units, time ranges, links, and geofences.
Confirm LAN DNS/TLS for both services and Tailscale HTTPS for Grafana. Grafana's anonymous Editor
access and lack of persistent UI edits are deliberate migration choices.

The app remains on 1.33.0, so disconnected status and Owner API 403 responses are expected until the
repair step. Do not count readiness probes or old dashboard data as restored collection. Initial
source inspection supports UID 568 with writable `/tmp`, but no local Docker daemon was available;
verify successful startup and absence of filesystem permission errors on Apollo.

Verify a completed Apollo base backup and uninterrupted WAL archiving before the repair. Record
an application version and UTC recovery point with the archived WAL segment, following
[upgrade recovery guidance](../docs/databases.md#recovery-points-before-application-upgrades).

## Repair recording after verified import

Prepare a separate reviewed change to a current stable TeslaMate release containing the 4.0.1 fix.
Read all intervening release notes, verify PostgreSQL support, and update pinned Grafana dashboard
sources to that same TeslaMate release. Review Grafana compatibility before changing its image.
The original application's startup command runs database migrations synchronously; retain the long
startup probe grace and never run two migration writers.

The upgrade crosses an `earthdistance` migration that can require superuser privileges. Inspect the
imported extension version and pending migration SQL first. If elevation is required, use a separately
approved, temporary migration procedure, then revoke it and verify the app role is non-superuser.
Never enable permanent application superuser access merely to get startup to succeed.

Verify fresh vehicle timestamps and a newly recorded drive or charge, successful token refresh,
restored address lookups, and corresponding Grafana panels. The upgrade is not complete until the
operator confirms live recording. Reauthentication, if required, is performed by the operator;
never place Tesla tokens in tools, chat, or repository files. Missed telemetry during the outage is
not recovered by copying the historical database.

## Cleanup and rollback

After historical data and Apollo backups are verified, remove the source ExternalSecret and import
patches. Keep the destination basic-auth Secret and an app-local patch setting
`spec.bootstrap.recovery.secret.name: teslamate-postgres`. The default
component recovery then uses the same password that Grafana consumes. Remove only the temporary
source vault item after verification. Preserve the database, its Kustomization, and backups.

Before application schema upgrades, rollback disables Apollo workloads/routes, confirms its pods
and tailnet proxy are gone, and then reverts the old disable PR. Old history is intact, but old
TeslaMate still has the API failure. Any Apollo-only changes are lost unless explicitly migrated back.
After an upgrade, do not point 1.33.0 at the upgraded database: recover a new cluster from the recorded
pre-upgrade recovery point with matching application/dashboard versions. Keep the failed database
and old cluster until recovery is verified; any deletion needs explicit approval.

Keep `postgres-lb` and its firewall path until all logical imports and rollback requirements are
finished. Keep the old app directories, Grafana configuration, and backup scaffold until Wave 2.
Archive this full record under `plans/done/` only after migration, repair, backup checks, and cleanup.

## Execution record

- Read-only source inspection: workloads and database Ready; API rejection and address TLS failures
  confirmed. Operator confirmed disconnected status and no recent data.
- Operator chose historical migration first, API repair on Apollo second, current Grafana access,
  and live database as the source of truth. Legacy SQL dump is obsolete.
- Manifests prepared in an isolated worktree. Cutover, runtime validation, backup verification,
  recording repair, and cleanup remain pending.
- Local validation passed: both cluster schema checks, 20 Conftest policy tests and 870 resource
  checks, full Apollo rendering (126 passed; existing suspended Paperless backup skipped), and
  targeted old-chart rendering confirming zero replicas and no Ingresses. Flate's linked-worktree
  source discovery failed locally; an identical standalone validation copy with a normal `.git`
  directory passed. No application configuration was changed to work around the renderer.
- Independent manifest review found no blocking defects. Runtime UID compatibility, actual import,
  network/TLS behavior, and recording remain deployment checks.

### Main shutdown and final backup, 2026-10-03 UTC

- Operator merged disable PR #322 as `6e673b9f4f2512bc8c004a62cdbb660aedb9f065`.
  Both Flux Kustomizations applied that revision. TeslaMate and Grafana have zero replicas, no pods,
  and no remaining Ingresses. The Grafana Tailscale proxy is absent, and the workstation's tailnet peer
  list contains no Grafana device. The source TeslaMate database has no remaining client connections.
- Main k8s-gateway returns NXDOMAIN for both names; Pi-hole also returns NXDOMAIN for Grafana.
  UniFi at `192.168.4.1` and `192.168.20.1` returns `192.168.6.10` for both names and a nonexistent
  control hostname. Both resolvers return Apollo's `192.168.21.100` for Paperless's explicit record,
  confirming the wildcard fallback behavior documented during that migration. The workstation also
  sees the fallback. Verify the new TeslaMate and Grafana records after Apollo deployment.
- With explicit operator approval, CNPG Backup `database/teslamate-final-20261003` completed using
  `barmanObjectStore` on shared `cnpg-cluster`. Backup ID `20261003T045814` ran from 04:58:14 to
  05:00:43 UTC, spanning WAL `000000010000028D00000026` through `000000010000028D00000027`.
  The next WAL, `000000010000028D00000028`, was archived at 05:00:46 UTC. Cluster readiness,
  continuous archiving, and last-backup success conditions were all True afterward.

### Apollo rollout and import cleanup, 2026-10-03 UTC

- Operator confirmed all three vault items were prepared, the source role was `teslamate`, and the
  destination archive path and server name were unused. All PR #323 checks passed. Three-node storage
  headroom and Apollo-to-source PostgreSQL connectivity were verified. A read-only dump under the
  source `teslamate` role completed successfully; its output was discarded.
- Operator merged PR #323 as `da774a5cb7521d01b1679c78d60988da1a8bfd87`. The import completed, and
  `teslamate-database`, `teslamate`, `grafana`, and `grafana-tailscale` became Ready at that revision.
- The private post-shutdown baseline matched all 13 table counts, 10 historical timestamp checks,
  and 94 schema migration versions immediately after import. Content hashes also matched for drives,
  charging processes, geofences, and settings. No tokens, locations, or vehicle details were published.
- The imported database and all public tables belong to `teslamate`; the role is not a superuser.
  `cube` remains 1.5, while `earthdistance` restored as 1.2 rather than the source's 1.1. Both extensions
  belong to `teslamate`. Account for the restored version when reviewing the later application upgrade.
- TeslaMate and Grafana are Ready without restarts. TeslaMate runs as UID/GID 568, database sessions use
  TLS 1.3, and startup logs showed no database connection, decryption, or filesystem permission errors.
  Owner API 403 responses persist as expected on 1.33.0; live recording is not repaired.
- Both UniFi resolvers and the workstation resolve the app names to `192.168.21.100`. Both LAN sites
  return HTTP 200 with valid TLS; Grafana's Tailscale hostname also passes HTTPS. Grafana exposes all
  22 provisioned dashboards, its datasource health check succeeds, and a historical drive/charge query
  returns successfully. Visual dashboard review remains an operator check.
- Apollo Backup `default/teslamate-pg-20261003051623` completed with ID `20261003T051855`, running from
  05:18:55 to 05:22:26 UTC. It spans WAL `000000010000000000000026` through
  `000000010000000000000053`. Last-backup success and continuous archiving conditions are True,
  with zero archive failures observed.
- Cleanup removes the source credential ExternalSecret and logical-import overrides. The shared
  component resumes recovery from the Apollo archive, with `teslamate-postgres` explicitly retained
  as the recovery credential so Grafana and PostgreSQL continue sharing the destination password.

Remaining work:

- [ ] Merge cleanup and verify Flux convergence and removal of the source Kubernetes Secret.
- [ ] Operator removes the temporary `hcc-apollo/teslamate-postgres-migration` vault item after cleanup.
- [ ] Review representative dashboard panels visually.
- [ ] Prepare the separate application/dashboard upgrade and verify fresh collection before archiving this plan.
