# Plan: Split CNPG Shared Cluster into Per-App Clusters

## Overview

**Status: folded into the Talos migration.** This split now happens *during* `plans/20260816-talos-migration.md`'s Wave 1, per-app, rather than as a standalone change on the current cluster: each new dedicated cluster (`teslamate-pg`, `paperless-pg`, `authentik-pg`) is created directly on the new Talos cluster, importing across the network from the old cluster's still-live `cnpg-cluster` instead of importing from a same-cluster source. This avoids splitting on the old cluster and then separately migrating three clusters to new infrastructure afterward. See that doc's "CNPG-backed apps" section for how this interleaves with the rest of the per-app cutover.

TODO: Decide whether pg clusters should be located in the database namespace or the app namespace (leaning towards app namespace).
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
teslamate-pg (database namespace)
└── teslamate database

paperless-pg (database namespace)
└── paperless database

authentik-pg (database namespace)
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

## Implementation Steps

### Step 1: Prepare - Scale Down Apps

Scale each app to 0 before importing its database to prevent writes during migration.

```bash
# For teslamate
kubectl scale deployment teslamate -n default --replicas=0
flux suspend helmrelease teslamate -n default
```

### Step 2: Create New Cluster with Import

Create `kubernetes/boreas/apps/database/cloudnative-pg/clusters/teslamate-pg/cluster.yaml`:

```yaml
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: teslamate-pg
  namespace: database
spec:
  instances: 1
  # Carried over from cnpg-cluster for illustration. Because logical import
  # crosses major versions, this is the point to move to a current major
  # instead of reproducing 16.2 — see "Why not Barman/WAL recovery".
  imageName: ghcr.io/cloudnative-pg/postgresql:16.2-10
  primaryUpdateStrategy: unsupervised

  storage:
    size: 10Gi
    storageClass: longhorn

  enableSuperuserAccess: true
  superuserSecret:
    name: cloudnative-pg-secrets

  postgresql:
    parameters:
      max_connections: "100"
      shared_buffers: 128MB

  bootstrap:
    initdb:
      database: teslamate
      owner: teslamate
      import:
        type: microservice
        databases:
          - teslamate
        source:
          externalCluster: cnpg-cluster-source

  externalClusters:
    - name: cnpg-cluster-source
      connectionParameters:
        # During the Talos migration this cluster is created on the new
        # cluster while the source is still on the old one, so this points
        # at the old cluster's external postgres-lb hostname rather than an
        # in-cluster DNS name. Reachable because the old cluster stays live
        # and routable across the dedicated migration VLAN.
        host: postgres.${SECRET_DOMAIN}
        user: postgres
        dbname: teslamate
      password:
        name: cloudnative-pg-secrets
        key: POSTGRES_SUPER_PASS

  backup:
    retentionPolicy: 30d
    barmanObjectStore:
      data:
        compression: bzip2
      wal:
        compression: bzip2
        maxParallel: 4
      destinationPath: s3://tf-hcc-cloudnativepg/
      endpointURL: https://${SECRET_CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com
      serverName: teslamate-pg-v1
      s3Credentials:
        accessKeyId:
          name: cloudnative-pg-secrets
          key: R2_ACCESS_KEY_ID
        secretAccessKey:
          name: cloudnative-pg-secrets
          key: R2_SECRET_ACCESS_KEY
```

### Step 3: Wait for Import Completion

Monitor the cluster status:

```bash
kubectl get cluster teslamate-pg -n database -w
```

Check logs for import progress:

```bash
kubectl logs -n database teslamate-pg-1 -f
```

The cluster will show `Cluster in healthy state` when import completes.

### Step 4: Update App Configuration

Update teslamate's database connection to use the new cluster.

In `kubernetes/boreas/apps/default/teslamate/app/helmrelease.yaml`, change:
```yaml
DATABASE_HOST: teslamate-pg-rw.database.svc.cluster.local
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
        value: teslamate-pg-rw.database.svc.cluster.local
```

### Step 5: Resume App and Verify

```bash
flux resume helmrelease teslamate -n default
kubectl scale deployment teslamate -n default --replicas=1
```

Verify connectivity:
```bash
kubectl logs -n default deployment/teslamate | head -50
```

### Step 6: Add Scheduled Backup

Create `kubernetes/boreas/apps/database/cloudnative-pg/clusters/teslamate-pg/scheduledbackup.yaml`:

```yaml
---
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: teslamate-pg-backup
  namespace: database
spec:
  schedule: "@daily"
  immediate: true
  backupOwnerReference: self
  cluster:
    name: teslamate-pg
```

### Step 7: Repeat for Other Databases

Repeat steps 1-6 for:
- **paperless-pg** (5Gi storage should suffice)
- **authentik-pg** (5Gi storage should suffice)

Adjust `max_connections` and `shared_buffers` based on each app's needs.

### Step 8: Decommission Old Cluster

After all apps are migrated and verified:

1. Keep old cluster running for 1-2 weeks as safety net
2. Take final backup of old cluster
3. Delete old cluster resources:

```bash
kubectl delete cluster cnpg-cluster -n database
kubectl delete scheduledbackup cnpg-cluster-backup -n database
```

### Step 9: Update Kustomization Dependencies

Update each app's kustomization to depend on its specific cluster:

```yaml
# teslamate kustomization
dependsOn:
  - name: teslamate-pg
  - name: longhorn
```

## Directory Structure After Migration

```
kubernetes/boreas/apps/database/cloudnative-pg/
├── operator/
│   ├── helmrelease.yaml
│   ├── kustomization.yaml
│   └── cloudnativepg.sops.yaml
└── clusters/
    ├── teslamate-pg/
    │   ├── cluster.yaml
    │   ├── scheduledbackup.yaml
    │   └── kustomization.yaml
    ├── paperless-pg/
    │   ├── cluster.yaml
    │   ├── scheduledbackup.yaml
    │   └── kustomization.yaml
    └── authentik-pg/
        ├── cluster.yaml
        ├── scheduledbackup.yaml
        └── kustomization.yaml
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
2. Point app config back to `cnpg-cluster-rw.database.svc.cluster.local`
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
- [ ] App functionality tested (login, create record, etc.)

## Dependencies

- CloudNativePG operator 1.20+ (import feature)
- Source cluster must remain running during import — during the Talos migration, this is `kubernetes/apollo`'s `postgres-lb` Service, reachable across the dedicated migration VLAN
- **Firewall rule: new HCC VLAN → `192.168.6.21:5432`**, open for the duration of the migration. `initdb.import` needs a live connection for `pg_dump`, and the new cluster sits on a different VLAN than the source. Without this, every import fails at bootstrap. Temporary — remove once all three apps have moved
- Sufficient Longhorn storage for new clusters

## k3s / Talos Compatibility

Distribution-agnostic — no k3s or Talos-specific considerations. Executed during the Talos migration (see Overview), but the import mechanism itself doesn't care which distribution either cluster runs.

## Estimated Downtime

Per app:
- ~5-10 minutes for small databases (paperless, authentik)
- ~10-20 minutes for teslamate (depends on data size)

Apps can be migrated one at a time to minimize overall impact.
