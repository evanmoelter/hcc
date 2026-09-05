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

### Backup-chain rehearsal (declined)

A one-off Barman restore into a throwaway cluster was also considered as a rehearsal of the R2 backup chain, and **declined**: during the migration the old cluster is itself the fallback, still running and never modified by an import, which is a stronger safety net than a restore test. Worth noting the residual: this leaves the R2 recovery path unexercised, so the first real use of those backups would also be the first proof they work. That matters only after the old cluster is decommissioned (Step 8), not during the migration.

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
| `<app>-pg` | Apollo's path, server name `<app>-pg-apollo-v1` | `spec.plugins`, the only writer |

The source store exists only for the cutover. Delete it once the app is verified on Apollo, so nothing can be pointed back at an archive the old cluster still owns.

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

## The postgres component owns the common shape

Apollo defines a `postgres` Kustomize component (see the migration plan's "Shared components"), so these three clusters are not three hand-written manifests. The component supplies the `Cluster`, its writing `ObjectStore`, the `ScheduledBackup`, and `dependsOn: cloudnative-pg`, parameterized by `${APP}`.

It defaults to `bootstrap.recovery`, which is right for a rebuild and wrong for a first import. The three splitting apps are a one-time case:

1. Label the app's Flux `Kustomization` `components.postgres/cnpg: init`, which replaces the component's `bootstrap` with a plain `initdb`.
2. Patch `initdb.import` and the source `externalClusters` entry onto it from the app's own directory, since both are specific to this cutover.
3. After the import completes and the first scheduled backup lands, remove the label and the patch. Future rebuilds then take the component's recovery default.

Steps 2 and 6 below show the resulting manifests in full, so the one-time shape is reviewable before it is written.

## Implementation Steps

### Step 1: Prepare - Disable the App on the Old Cluster

The app must stop writing before its database is imported. During the Talos migration this is the **disable** step defined in `plans/20260816-talos-migration.md` — a commit merged to `kubernetes/main` that scales the workload to zero and removes the app's external and tailscale Ingresses, releasing its DNS and tailnet names. It is a merged change, not a `kubectl scale`, so the state is reconcilable and revertible.

The app's directory, PVC, and data stay in `kubernetes/main`, disabled but intact, until the old cluster is decommissioned in Wave 2.

### Step 2: Create New Cluster with Import

The cluster lives in the app's namespace, alongside the app, per the decision recorded in the Overview. Compose it from the `postgres` component and add only what is specific to this one-time import.

`kubernetes/apollo/apps/default/teslamate/ks.yaml`:

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app teslamate
  labels:
    components.postgres/cnpg: init
spec:
  components:
    - ../../../../components/postgres
  postBuild:
    substitute:
      APP: *app
```

`kubernetes/apollo/apps/default/teslamate/app/objectstore-source.yaml`, read only, pointing at the archive the old cluster wrote:

```yaml
---
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: teslamate-pg-source
spec:
  configuration:
    destinationPath: s3://tf-hcc-cloudnativepg/
    endpointURL: https://${SECRET_CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com
    s3Credentials:
      accessKeyId:
        name: cloudnative-pg-secrets
        key: R2_ACCESS_KEY_ID
      secretAccessKey:
        name: cloudnative-pg-secrets
        key: R2_SECRET_ACCESS_KEY
```

The import itself is patched onto the component's `Cluster` from the app's `kustomization.yaml`:

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./objectstore-source.yaml
patches:
  - target:
      group: postgresql.cnpg.io
      version: v1
      kind: Cluster
    patch: |-
      - op: add
        path: /spec/bootstrap/initdb/import
        value:
          type: microservice
          databases:
            - teslamate
          source:
            externalCluster: cnpg-cluster-source
      - op: add
        path: /spec/externalClusters
        value:
          - name: cnpg-cluster-source
            connectionParameters:
              host: 192.168.6.21
              user: postgres
              dbname: teslamate
            password:
              name: cloudnative-pg-secrets
              key: POSTGRES_SUPER_PASS
```

`host` is the old cluster's `postgres-lb` address rather than a DNS name. External-dns never watched Services on the old cluster, so `postgres.${SECRET_DOMAIN}` resolves only through k8s-gateway, which is itself in flux during the migration. The raw address is reachable across the temporary firewall rule in Dependencies.

The image comes from the component. Because logical import crosses major versions, this is the point to choose a current major rather than reproducing 16.2 — see "Why not Barman/WAL recovery" and the per-app version gate above.

Recovery for an app that is *not* importing, such as Mealie or Home Assistant, uses the plugin form instead of a patch:

```yaml
externalClusters:
  - name: mealie-pg-source
    plugin:
      name: barman-cloud.cloudnative-pg.io
      parameters:
        barmanObjectName: mealie-pg-source
        serverName: mealie-pg-v1
```

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

### Step 6: Add Scheduled Backup

The `postgres` component supplies the `ScheduledBackup` and the writing `ObjectStore`, so nothing is written per app. Both use the plugin form:

```yaml
---
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: ${APP}-pg-daily
spec:
  schedule: "0 40 4 * * *"
  immediate: true
  backupOwnerReference: self
  cluster:
    name: ${APP}-pg
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
```

Confirm the first backup lands before removing the `components.postgres/cnpg: init` label. Until it does, the component's recovery default has nothing to recover from, and a rebuild would fail rather than restore.

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
# teslamate kustomization
dependsOn:
  - name: longhorn
```

The `postgres` component adds `dependsOn: cloudnative-pg` itself, and the cluster is now rendered by the same Kustomization as the app, so there is no separate `teslamate-pg` Kustomization to depend on. Readiness is gated by the component's `healthCheckExprs` on the CNPG `Cluster` instead.

## Directory Structure After Migration

Each cluster sits with its app, not under a shared `database` directory:

```
kubernetes/apollo/
├── components/
│   └── postgres/            Cluster, writing ObjectStore, ScheduledBackup, dependsOn
└── apps/
    ├── database/
    │   └── cloudnative-pg/
    │       ├── operator/
    │       └── barman-plugin/
    ├── default/
    │   ├── teslamate/
    │   │   ├── ks.yaml                        components + APP substitution
    │   │   └── app/
    │   │       ├── objectstore-source.yaml    cutover only; deleted after verification
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
- [ ] `components.postgres/cnpg: init` label and the one-time import patch removed after the first backup
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
