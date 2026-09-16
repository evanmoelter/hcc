# Apollo databases

The Barman plugin must share the CNPG operator's namespace for service discovery and mutual TLS.
Keep the upstream chart's service and certificate names; they are part of that integration.
See the [upstream requirements](https://cloudnative-pg.io/plugin-barman-cloud/docs/installation/).

Use the [Postgres component](../kubernetes/apollo/components/postgres/) from a separate database
Kustomization in the app namespace. Copy the [tested satellite](../tests/fixtures/postgres/ks-cluster.yaml),
including its platform dependencies and readiness check, and make the app depend on that Kustomization.
Health checks cannot order resources applied by the same Kustomization. `Ready=False` during bootstrap
means wait; it is not a terminal failure.

Set `APP` and a tag-and-digest-pinned `POSTGRES_IMAGE` per app. Check the source PostgreSQL major and
extensions before physical recovery. Set `POSTGRES_DATABASE` and `POSTGRES_USERNAME` when they differ
from `APP` (Home Assistant uses `home_assistant`). CNPG creates `${APP}-pg-app` connection credentials;
backups do not include Kubernetes Secrets, so recovery configures the application owner again.

The tested upstream `system-trixie` image has PostgreSQL UID 26/GID 102; UID 568 has no passwd entry and
cannot run `initdb`. Override `POSTGRES_UID`/`POSTGRES_GID` when choosing an image with a different identity.

Defaults and optional `POSTGRES_*` substitutions live in the component. Use a six-field cron expression
(seconds first) for `POSTGRES_BACKUP_SCHEDULE`. Weekly base backups plus continuous WAL archiving provide
PIT recovery; retention is a recovery window, not an exact deletion age. Native Kustomize patches handle
app-specific PostgreSQL settings, extensions, and recovery targets.

Before the first consumer, the operator creates these 1Password items in `hcc-apollo`:

| Item | Fields |
|---|---|
| `cloudflare-r2` (shared with VolSync) | `ACCOUNT_ID` |
| `cnpg-r2` | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`; Object Read & Write on `tf-hcc-apollo-cnpg` only |

ESO constructs the private endpoint; Barman receives it through `AWS_ENDPOINT_URL_S3` from the generated
Secret. Source and destination stores share that endpoint during migration. A different source account
needs an explicit source `endpointURL`, because the plugin shares environment variables between stores.

The default bootstrap recovers from the app's Apollo archive. For a new database, add the
[initialization component](../kubernetes/apollo/components/postgres/init/) after the base in its database Kustomization:

```yaml
spec:
  components:
    - ../../../../components/postgres
    - ../../../../components/postgres/init
```

For a logical import, use only the base component and replace
`spec.bootstrap` and `spec.externalClusters` in the app's build; also remove `cnpg.io/skipEmptyWalArchiveCheck`.
For physical migration, add a temporary source ObjectStore with no retention policy and separate read-only
old-bucket credentials, then point `externalClusters[].plugin` at it with the old server name.

After checking app data and the first Apollo backup, remove the init component reference, import patch, or temporary
source configuration and credentials. Keep the Cluster and its owning Kustomization. The default recovery
bypasses the empty-archive check to reuse its own archive; never run another writer against that server name.
Cluster pruning is disabled, so removing the component does not delete its database.

## Backup and recovery verification

Operator deployment, plugin registration, certificates, and the operator scrape were verified on 2026-09-13.
The disposable `cnpg-smoke` rehearsal verified Apollo backup and recovery on 2026-09-15–16 UTC using
PostgreSQL 18.1, CNPG 1.30.0, and Barman Cloud plugin 0.15.0. The
[component fixtures](../tests/test_postgres_component.py) continue to cover rendering and bootstrap configuration.

The live run passed initialization, application authentication, a seeded base backup, post-backup WAL
replay onto fresh storage, authentication with recreated application credentials, new writes after recovery,
and a backup of the restored database. Point-in-time targets, multi-instance failover, and recovery from
the old cluster's in-tree Barman archive remain unverified; Mealie's migration will test that archive path.

### Run evidence

All completion times below are UTC. Each backup reached `completed` through the Barman plugin.

| Backup | Backup ID | Completed |
|---|---|---|
| Initial scheduled backup | `20260915T213601` | 2026-09-15 21:36:08 |
| `cnpg-smoke-seed` | `20260915T215741` | 2026-09-15 21:57:50 |
| `cnpg-smoke-restored` | `20260916T043810` | 2026-09-16 04:38:15 |

Each SQL Job checked the exact expected records. The checksums are MD5 over ordered `id:payload` pairs.

| Completed Job | Rows | Checksum |
|---|---|---|
| `cnpg-smoke-seed-v2` | 1,000 | `d550ccd7b455b94ba92e911a03de6cb8` |
| `cnpg-smoke-wal` | 1,000 | `9d581269d82da82678be38ce4338d570` |
| `cnpg-smoke-verify` | 1,000 | `15b7611293b2064a36c35a1c9ec917cf` |

The WAL Job updated, deleted, and inserted 100 rows each after the seed backup. Its committed segment
`00000001000000000000000E` was archived, and the recovery logs confirmed replay of that segment before
promotion to timeline 2. The verifier authenticated using the recreated `cnpg-smoke-pg-app` Secret and
checked the recovered dataset before making another 100 updates, deletes, and inserts. Its new segment
`000000020000000000000012` archived successfully; the restored backup used timeline 2.

| Resource | Original UID | Restored UID |
|---|---|---|
| Cluster | `248f8c88-3be3-4de0-a49e-2f5ceceb448a` | `fa34026d-a389-46c9-bd78-3b65bd8e8ffd` |
| PVC | `e5e05ac0-bcde-4fa6-9e86-11a75dcf9b2a` | `18163c67-31a9-4755-bae0-5ea125e13882` |

Before recovery and again at retirement, read-only checks confirmed the Cluster, pods, PVC/PV, and
associated Longhorn volume, engine, and replicas were absent. The
[removal](https://github.com/evanmoelter/hcc/pull/279) and
[retirement](https://github.com/evanmoelter/hcc/pull/282) revisions retained the ObjectStore and ExternalSecret
until shutdown and storage removal finished. Flux Ready alone did not establish that deletion had completed.

The workload and Kubernetes scaffolding are removed by the
[final cleanup](https://github.com/evanmoelter/hcc/pull/283). R2 deletion is separate operator work:
`s3://tf-hcc-apollo-cnpg/cnpg-smoke/` remains until explicitly removed. Confirm that prefix is empty before
repeating initialization with the same archive identity; retention does not clean up a retired database.

### Observed issues

The first seed attempt failed because Flux substitution changed SQL dollar-quote delimiters from `$$` to `$`.
Its transaction rolled back and the dependent backup stayed blocked. The
[corrective PR](https://github.com/evanmoelter/hcc/pull/284) disabled substitution for the SQL ConfigMaps and
created `cnpg-smoke-seed-v2` for the retry. A regression test reproduced the failure with Flux substitution
enabled and was removed with the disposable SQL files during cleanup.

The first post-restore workload WAL archived at 23:20:05 UTC, alongside the first timed checkpoint,
about five minutes after PostgreSQL started despite `archive_timeout=60s`. The ten-minute verifier wait
passed without intervention. The cause was not isolated; this run does not establish a one-minute upper
bound on archive latency immediately after recovery.

SQL ConfigMaps containing dollar-quoted blocks need the annotation
`kustomize.toolkit.fluxcd.io/substitute: disabled`: Flux substitution otherwise reduces `$$` to `$`.
Render SQL with post-build variables enabled when validating it locally; dry-run builds omit values
loaded from cluster Secrets and ConfigMaps and can skip substitution entirely.

[Storage](storage.md#r2-backup-separation) records backup bucket separation.
The [migration plan](../plans/20260816-talos-migration.md) tracks per-app cutovers.
