# Apollo databases

The Barman plugin must share the CNPG operator's namespace for service discovery and mutual TLS.
Keep the upstream chart's service and certificate names; they are part of that integration.
See the [upstream requirements](https://cloudnative-pg.io/plugin-barman-cloud/docs/installation/).

Use the [Postgres component](../kubernetes/apollo/components/postgres/) from a separate database
Kustomization in the app namespace. Copy the [tested satellite](../tests/fixtures/postgres/ks-cluster.yaml),
including its platform dependencies and readiness check, and make the app depend on that Kustomization.
Health checks cannot order resources applied by the same Kustomization. `Ready=False` during bootstrap
means wait; it is not a terminal failure.

`cluster-apps` skips parent substitution to preserve the initialization patch's `$${...}` expressions;
variables added there must be intended for downstream builds, since the parent will leave them unexpanded.

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

The default bootstrap recovers from the app's Apollo archive. For a new database, label its
database Kustomization `components.postgres/cnpg: init`. For a logical import, omit that label and replace
`spec.bootstrap` and `spec.externalClusters` in the app's build; also remove `cnpg.io/skipEmptyWalArchiveCheck`.
For physical migration, add a temporary source ObjectStore with no retention policy and separate read-only
old-bucket credentials, then point `externalClusters[].plugin` at it with the old server name.

After checking app data and the first Apollo backup, remove the init label, import patch, or temporary
source configuration and credentials. Keep the Cluster and its owning Kustomization. The default recovery
bypasses the empty-archive check to reuse its own archive; never run another writer against that server name.
Cluster pruning is disabled, so removing the component does not delete its database.

Operator deployment, plugin registration, certificates, and the operator scrape were verified on 2026-09-13.
Database backup and recovery remain unverified; Mealie is the first proof that the plugin can read the
old cluster's in-tree Barman archive. The [local fixtures](../tests/test_postgres_component.py) exercise
rendering and bootstrap cleanup without deploying a database.

[Storage](storage.md#r2-backup-separation) records backup bucket separation.
The [migration plan](../plans/20260816-talos-migration.md) tracks per-app cutovers.
