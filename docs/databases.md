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

## SQL workloads

SQL ConfigMaps containing dollar-quoted blocks need the annotation
`kustomize.toolkit.fluxcd.io/substitute: disabled`: Flux substitution otherwise reduces `$$` to `$`.
Render SQL with post-build variables enabled when validating it locally; dry-run builds omit values
loaded from cluster Secrets and ConfigMaps and can skip substitution entirely.

The [completed rehearsal](../plans/done/20260915-cnpg-rehearsal.md) records backup and recovery coverage,
observed limitations, and execution evidence.

[Storage](storage.md#r2-backup-separation) records backup bucket separation.
The [migration plan](../plans/20260816-talos-migration.md) tracks per-app cutovers.

## Dragonfly

Apollo installs the upstream Dragonfly operator chart in `database`; the chart owns its CRD and RBAC.
Its ServiceMonitor scrapes the operator's internal HTTP metrics endpoint with the chart's RBAC proxy disabled,
matching Apollo's other controller metrics. Any pod that can reach the endpoint can scrape it without credentials.
Operator readiness and its Prometheus target still need deployment verification.

Dragonfly instances belong to their consuming apps and are added during app migration. Paperless gets a
fresh memory-only instance with a password supplied through ESO from `hcc-apollo`; define its ExternalSecret
and 1Password field alongside that migration. The operator alone requires no application credentials.
Authentik no longer needs Redis as of [2025.10](https://docs.goauthentik.io/releases/2025.10/#redis-removal),
so its old Redis configuration and Flux dependency are not carried forward. The old shared Dragonfly stays
running while Paperless still uses it.

Each instance needs its own Flux Kustomization, depending on `dragonfly-operator` and `onepassword-store`,
with a health expression waiting for `status.phase == 'Ready'`. Apply the pod and container security contexts
explicitly: the operator's own Helm settings do not harden the instances it creates. Leave memory headroom
between Dragonfly's `maxmemory` and the container limit.

The operator's generated NetworkPolicy allows client access only within the instance namespace and limits
the admin port to the operator and peer pods. Add a narrow rule for Prometheus to scrape TCP 9999 when adding
an instance PodMonitor. Replication improves availability but does not provide a backup; drain Paperless's
pending jobs before its cutover to the fresh instance.

The operator chart approach follows [Mafyuh](https://github.com/Mafyuh/iac/tree/main/kubernetes/apps/databases/dragonfly-operator),
and per-app instances follow [joryirving](https://github.com/joryirving/home-ops/tree/main/kubernetes/components/dragonfly).
See the [upstream operator](https://github.com/dragonflydb/dragonfly-operator) for instance configuration.
