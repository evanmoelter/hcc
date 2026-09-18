# Plan: Split CNPG Shared Cluster into Per-App Clusters

## Overview

**Status: folded into the Talos migration, and partly already done.** This split now happens *during* `plans/20260816-talos-migration.md`'s Wave 1, per-app, rather than as a standalone change on the current cluster: each new dedicated cluster (`teslamate-pg`, `paperless-pg`, `authentik-pg`) is created directly on the new Talos cluster, importing across the network from the old cluster's still-live `cnpg-cluster` instead of importing from a same-cluster source. This avoids splitting on the old cluster and then separately migrating three clusters to new infrastructure afterward. See that doc's "Rebuild (database-backed apps)" section for how this interleaves with the rest of the per-app cutover.

**Two apps have already been split ahead of this plan.** `mealie-pg` and `home-assistant-pg` now exist as independent clusters on PG 18.1, defined alongside their apps in `kubernetes/main/apps/default/{mealie,home-assistant}/app/cluster.yaml`, each with its own Barman backup to R2 and its own `ScheduledBackup`. They are not part of the remaining split work. Their migration is a Barman recovery rather than a logical import, since each instance already holds exactly one database; the Talos migration doc covers that path and the empty-database trap that comes with copying their `bootstrap.initdb` manifests forward.

~~TODO: Decide whether pg clusters should be located in the database namespace or the app namespace (leaning towards app namespace).~~ **Resolved**: app namespace. `mealie-pg` and `home-assistant-pg` are both defined in the app's own directory and namespace, which settles the question by precedent. Follow that for `teslamate-pg`, `paperless-pg`, and `authentik-pg` unless a specific reason argues otherwise. Note this makes ESO the mechanism for cross-namespace access (Grafana reading teslamate's credentials), which is the resolution recorded below.
~~TODO: figure out how secrets will be handled across namespaces. For example, how will the teslamate db secret be used by grafana? Maybe it's finally time for 1Password?~~ **Resolved**: External Secrets Operator + 1Password, adopted as part of the Talos migration (`plans/20260816-talos-migration.md`). Cross-namespace access becomes an `ExternalSecret` in each consuming namespace pointing at the same 1Password item, rather than a Secret-copying workaround.

Migrate from a single shared CloudNativePG cluster (`cnpg-cluster`) serving multiple applications to dedicated per-app clusters. This improves backup isolation, simplifies upgrades, and follows the microservice database pattern.

## Problem

The current setup has one CNPG cluster hosting three databases:
- `teslamate` - EV tracking data
- `paperless` - Document management
- `authentik` - SSO/authentication

This creates issues:
- **Backup granularity**: Full cluster backups include all databases, making point-in-time recovery for a single app difficult
- **Upgrade risk**: PostgreSQL upgrades affect all apps simultaneously
- **Resource contention**: All apps share the same instance resources
- **Blast radius**: A corrupted database or misconfiguration affects all apps

## Current State

```
cnpg-cluster (database namespace)
├── teslamate database
├── paperless database
└── authentik database
```

- **Image**: `ghcr.io/cloudnative-pg/postgresql:16.2-10`
- **Storage**: 20Gi on Longhorn
- **Backups**: Daily to Cloudflare R2
- **Extensions in use**:
  - teslamate: `cube`, `earthdistance`, `plpgsql`
  - paperless: `plpgsql` only
  - authentik: `plpgsql` only

## Target State

```
teslamate-pg (default namespace, alongside the app)
└── teslamate database

paperless-pg (default namespace, alongside the app)
└── paperless database

authentik-pg (security namespace, alongside the app)
└── authentik database
```

Each cluster gets:
- Independent backup schedule and retention
- Isolated storage allocation
- Separate upgrade path
- Own connection pool settings

## Implementation Approach

Use CNPG's [database import](https://cloudnative-pg.io/docs/1.28/database_import/) feature with the **microservice** method. This performs a logical backup (`pg_dump`) from the source cluster and restores into the new dedicated cluster.

### Why Database Import vs Other Methods

| Method | Pros | Cons |
|--------|------|------|
| **CNPG Import (chosen)** | Declarative, handles orchestration, optimized performance | Requires app downtime during import |
| Manual pg_dump/restore | Simple, well-understood | Manual process, more error-prone |
| Barman/WAL recovery from R2 | Fast, no source connection needed, PITR-capable | **Physical — whole-instance only, cannot split** (see below) |
| pg_basebackup | Fast for large DBs | Copies entire cluster, not per-database |
| Logical replication | Minimal downtime | Complex setup, overkill for this size |

### Why not Barman/WAL recovery

This deserves calling out separately, because the commented-out scaffold in `cluster.yaml` already shows the `bootstrap.recovery` + `externalClusters.barmanObjectStore` pattern, and daily backups to R2 already exist — so recovery looks like the obvious path until you notice it can't do this job.

Barman recovery is **physical**: it replays a base backup plus WAL into a data directory, reproducing the instance byte-for-byte. There is no way to select one database out of it. Recovering `cnpg-cluster` into `teslamate-pg` would produce an instance containing teslamate *and* paperless *and* authentik, requiring two `DROP DATABASE` statements afterward — three times over, once per app, each transiently carrying the full 20Gi footprint. Splitting is a *logical* reorganization, so it needs a logical mechanism. That's decisive on its own.

Two secondary differences reinforce it:

- **Major version.** `pg_dump`/restore crosses PostgreSQL major versions; physical recovery does not — it pins the new cluster to 16.x and requires a matching image. Since the current image is `16.2-10` (a February 2024 patch release), import makes the major-version upgrade available here, whereas recovery defers it to a later logical dump/restore — paying the same cost twice. See "PostgreSQL version compatibility is a per-app gate" below: the upgrade is cheap in *mechanism*, not automatically free in practice.
- **Bloat.** Import rebuilds indexes and leaves no accumulated bloat; physical recovery carries the existing on-disk state over exactly.

What Barman recovery would have bought — independence from the source cluster, and no cross-VLAN network path — is real but not needed: the source cluster stays live throughout the migration by design, and the firewall rule is a one-line addition (see Dependencies).

### PostgreSQL version compatibility is a per-app gate

The major-version jump is not automatically free: TeslaMate, Paperless-ngx, and Authentik each support a specific range of PostgreSQL versions, and landing on a current major may require bumping the app itself. That app bump is its own change with its own schema migrations, not a version-string edit.

**Deliberately not resolved now.** Supported ranges move with every app release, so any answer written here would be stale by the time the app actually migrates. This is a **pre-flight check performed immediately before each app's cutover**, against that app's release notes at that moment — not a decision made once for all three upfront.

Three things make this cheaper than it sounds:

- **The apps don't have to agree.** Each app now gets its own cluster, so `teslamate-pg`, `paperless-pg`, and `authentik-pg` can land on different majors. Under the shared `cnpg-cluster` a single lagging app would have held all three back; after the split it holds back only itself. One app being stuck is not a reason to keep the others on 16.
- **The app bump can be decoupled.** If an app needs a newer version to support the target major, bump it **on the old cluster first**, against the existing PG 16 — then the migration changes only PG major and cluster, with the app version already proven in place. Otherwise the cutover changes app version, PostgreSQL major, and Kubernetes cluster simultaneously, and any failure is hard to attribute.
- **Staying on 16 is always a valid answer.** If an app's compatibility is unclear or its bump looks disruptive, import into a 16.x cluster and treat the major upgrade as separate later work. The split still succeeds; only the free-upgrade side benefit is deferred.

Independently of the app, confirm `cube` and `earthdistance` (teslamate's extensions; `earthdistance` depends on `cube`) ship in the CNPG image for whichever major is chosen.

### Backup-chain rehearsal

The [CNPG rehearsal](done/20260915-cnpg-rehearsal.md) exercised Apollo's plugin backup and recovery path
with a disposable SQL workload before app migration. Mealie still proves recovery from the old
cluster's in-tree Barman archive.

## Backups move to the Barman Cloud plugin

CNPG deprecated the in-tree `barmanObjectStore` in 1.26 and will remove it. Backup and recovery move to the [Barman Cloud plugin](https://cloudnative-pg.io/plugin-barman-cloud/docs/migration/), which speaks the same object-store format through the CNPG-I plugin interface. Apollo's clusters are all new, so they are written against the plugin from the start; `kubernetes/main` is never converted, because the old cluster has weeks left and a backup-system change is the last thing to make to a rollback target.

Community examples, including the reference repos surveyed for this migration, still show the in-tree form. Prefer upstream's migration guide over a copied manifest.

### What changes

| In-tree | Plugin |
|---|---|
| `Cluster.spec.backup.barmanObjectStore` | `ObjectStore.spec.configuration`, a namespaced CR |
| `Cluster.spec.backup.retentionPolicy` | `ObjectStore.spec.retentionPolicy` |
| WAL archiving implied by `backup` | `Cluster.spec.plugins[]` with `isWALArchiver: true` |
| `ScheduledBackup.spec.method` default | `method: plugin` plus `pluginConfiguration` |
| `externalClusters[].barmanObjectStore` | `externalClusters[].plugin`, naming an `ObjectStore` and a `serverName` |

A cluster references its store by name:

```yaml
spec:
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: teslamate-pg
```

`ObjectStore` is namespaced and must sit with its `Cluster`, which fits the app-namespace decision above: each app namespace holds its cluster and its store.

### Two stores per migrating app

The migration's rule that exactly one cluster writes each archive survives as two `ObjectStore` resources in the app's namespace:

| Store | Points at | Used by |
|---|---|---|
| `<app>-pg-source` | the old cluster's `destinationPath` and server name | `externalClusters[].plugin`, read only |
| `<app>-pg` | `s3://tf-hcc-apollo-cnpg/<app>/`, server name `<app>-pg-apollo-v1` | `spec.plugins`, the only writer |

The source store exists only for the cutover. Delete it once the app is verified on Apollo, so nothing can be pointed back at an archive the old cluster still owns.
Use separate source and destination credentials, with Apollo's backup credential scoped to its CNPG bucket.
[Apollo storage](../docs/storage.md#r2-backup-separation) records the bucket layout and credential handoff.

### Prerequisites

- CNPG operator 1.26 or newer. Apollo installs a current release, so this is satisfied by default rather than by upgrade.
- cert-manager, which the plugin uses for its own serving certificates. This adds an edge to the Phase B bootstrap order in the migration plan: CNPG's backup path now waits on cert-manager, where the operator alone did not.
- The plugin deploys into the CNPG **operator's** namespace, not the app's. Apollo's operator namespace is the one to install it in.

### Monitoring

Three metrics are renamed, so any alert or dashboard carried forward needs updating:

| Before | After |
|---|---|
| `cnpg_collector_last_failed_backup_timestamp` | `barman_cloud_cloudnative_pg_io_last_failed_backup_timestamp` |
| `cnpg_collector_last_available_backup_timestamp` | `barman_cloud_cloudnative_pg_io_last_available_backup_timestamp` |
| `cnpg_collector_first_recoverability_point` | `barman_cloud_cloudnative_pg_io_first_recoverability_point` |

The backup gate in the migration plan reads the **old** cluster's metrics, which keep their existing names. Only Apollo's alerts change.

## The postgres component

The shared component is implemented. [Apollo databases](../docs/databases.md) records its usage,
credentials, readiness, and bootstrap cleanup. The remaining work is per-app migration below.

## Implementation Steps

### Step 1: Prepare - Disable the App on the Old Cluster

The app must stop writing before its database is imported. During the Talos migration this is the **disable** step defined in `plans/20260816-talos-migration.md` — a commit merged to `kubernetes/main` that scales the workload to zero and removes the app's external and tailscale Ingresses, releasing its DNS and tailnet names. It is a merged change, not a `kubectl scale`, so the state is reconcilable and revertible.

The app's directory, PVC, and data stay in `kubernetes/main`, disabled but intact, until the old cluster is decommissioned in Wave 2.

### Step 2: Create New Cluster with Import

Compose the Postgres component in the app namespace using the
[database satellite example](../tests/fixtures/postgres/ks-database.yaml). Choose the image and storage
for the app; physical restore requires the source major, while logical import can cross majors after
checking application compatibility and extensions.

For TeslaMate, Paperless, and Authentik, replace `spec.bootstrap` with `initdb.import` using the
`microservice` method and only the app's database. Replace `spec.externalClusters` with a connection
to `192.168.6.21:5432`, using a separate operator-provided import Secret. Remove
`cnpg.io/skipEmptyWalArchiveCheck` so the new database must start with an empty destination archive.
Put these patches in the app's `database/kustomization.yaml`, using only the base Postgres component.
The optional `postgres/init` component is for empty databases, not imports.

A logical import does not need a source ObjectStore. Mealie and Home Assistant instead use physical
recovery with a temporary source ObjectStore and read-only old-bucket credentials, as described in
[the recovery lifecycle](../docs/databases.md). Both methods keep writing only to Apollo's archive.

### Step 3: Wait for Import Completion

Monitor the cluster status:

```bash
kubectl get cluster teslamate-pg -n default -w
```

Check logs for import progress:

```bash
kubectl logs -n default teslamate-pg-1 -f
```

The cluster will show `Cluster in healthy state` when import completes.

### Step 4: Update App Configuration

Update teslamate's database connection to use the new cluster.

In `kubernetes/apollo/apps/default/teslamate/app/helmrelease.yaml`, change:
```yaml
DATABASE_HOST: teslamate-pg-rw.default.svc.cluster.local
```

Update the init container (no longer needed for database creation, but keep for connection test):
```yaml
initContainers:
  - name: init-db
    image: ghcr.io/onedr0p/postgres-init:16.2
    envFrom:
      - secretRef:
          name: teslamate-secret
    env:
      - name: INIT_POSTGRES_HOST
        value: teslamate-pg-rw.default.svc.cluster.local
```

### Step 5: Bring the App Up on the New Cluster and Verify

The app is authored fresh under `kubernetes/apollo`, so Flux brings it up on reconcile — there is nothing to resume. Verify it *before* attaching the routing that publishes its real hostname:

```bash
kubectl logs -n default deployment/teslamate | head -50
kubectl port-forward -n default deployment/teslamate 4000:4000  # spot-check data
```

### Step 6: Verify the First Backup and Remove Bootstrap Overrides

The component creates an immediate base backup and the recurring schedule. Confirm the app's data and
first Apollo backup before removing the import patch or temporary physical-restore source and credentials.
Future rebuilds then recover from Apollo's archive. Keep the same Cluster and database Kustomization.

### Step 7: Repeat for Other Databases

Repeat steps 1-6 for:
- **paperless-pg** (5Gi storage should suffice)
- **authentik-pg** (5Gi storage should suffice)

Adjust `max_connections` and `shared_buffers` based on each app's needs.

### Step 8: Decommission the Old Cluster

Executed as part of the Talos migration's Wave 2, not as a separate step here: `cnpg-cluster` is not deleted piecemeal — it goes away with the whole `kubernetes/main` tree once every app is verified on the new cluster. Keeping it running (and backing up) in the meantime is exactly the safety net rollback depends on.

Take a final backup of the old cluster before the Wave 2 teardown, then delete the tree rather than issuing `kubectl delete` against individual resources.

### Step 9: Update Kustomization Dependencies

Update each app's kustomization to depend on its specific cluster:

```yaml
# teslamate ks.yaml
dependsOn:
  - name: teslamate-cluster
  - name: longhorn
```

`teslamate-cluster` is the satellite Kustomization from Step 2, and this dependency is what holds the app back until the import finishes. The satellite depends on `plugin-barman-cloud`, `longhorn-config`, and `onepassword-store`.

## Directory Structure After Migration

Each cluster sits with its app, not under a shared `database` directory:

```
kubernetes/apollo/
├── components/
│   └── postgres/            Cluster, writing ObjectStore, ScheduledBackup, ExternalSecret
└── apps/
    ├── database/
    │   └── cloudnative-pg/
    │       ├── app/
    │       └── barman/
    ├── default/
    │   ├── teslamate/
    │   │   ├── ks.yaml                        dependsOn the satellite below
    │   │   ├── ks-database.yaml               components + APP; wait + healthCheckExprs
    │   │   ├── app/
    │   │   └── database/
    │   │       └── kustomization.yaml         one-time import patch
    │   └── paperless/
    └── security/
        └── authentik/
```

## Resource Sizing Recommendations

| Cluster | Storage | Max Connections | Shared Buffers |
|---------|---------|-----------------|----------------|
| teslamate-pg | 20Gi | 100 | 128MB |
| paperless-pg | 5Gi | 50 | 64MB |
| authentik-pg | 2Gi | 100 | 64MB |

Total storage: 20Gi (same as before, but isolated)

## Rollback Plan

If migration fails for any app:

1. Scale down the app
2. Point app config back to the old cluster's `cnpg-cluster-rw` in its `database` namespace
3. Scale app back up
4. Delete the failed new cluster
5. Investigate and retry

The old cluster remains untouched during migration, so rollback is safe.

## Testing Checklist

Before each app's cutover (pre-flight):
- [ ] Check that app version's supported PostgreSQL range against the target major, in its current release notes
- [ ] If a newer app version is required, bump it on the old cluster against PG 16 first, so the migration changes only PG major and cluster
- [ ] Confirm required extensions exist in the CNPG image for the chosen major (`cube`, `earthdistance` for teslamate)

For each migrated app:
- [ ] App connects successfully to new cluster
- [ ] Data integrity verified (spot check records)
- [ ] Scheduled backup runs successfully
- [ ] Backup appears in R2 bucket under new serverName
- [ ] One-time import patch removed after the first backup lands
- [ ] Source `ObjectStore` deleted once the app is verified
- [ ] App functionality tested (login, create record, etc.)

## Dependencies

- CloudNativePG operator 1.26 or newer, for the Barman Cloud plugin. The import feature itself needs only 1.20
- The Barman Cloud plugin, installed in the operator's namespace, and cert-manager before it
- Source cluster must remain running during import — during the Talos migration, this is the **old** cluster's (`kubernetes/main`) `postgres-lb` Service, reachable across the dedicated migration VLAN
- **Firewall rule: new HCC VLAN → `192.168.6.21:5432`**, open for the duration of the migration. `initdb.import` needs a live connection for `pg_dump`, and the new cluster sits on a different VLAN than the source. Without this, every import fails at bootstrap. Temporary — remove once all three apps have moved
- Sufficient Longhorn storage for new clusters

## k3s / Talos Compatibility

Distribution-agnostic — no k3s or Talos-specific considerations. Executed during the Talos migration (see Overview), but the import mechanism itself doesn't care which distribution either cluster runs.

## Estimated Downtime

Per app:
- ~5-10 minutes for small databases (paperless, authentik)
- ~10-20 minutes for teslamate (depends on data size)

Apps can be migrated one at a time to minimize overall impact.
