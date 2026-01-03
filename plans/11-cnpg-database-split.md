# Plan: Split CNPG Shared Cluster into Per-App Clusters

## Overview

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
| pg_basebackup | Fast for large DBs | Copies entire cluster, not per-database |
| Logical replication | Minimal downtime | Complex setup, overkill for this size |

## Implementation Steps

### Step 1: Prepare - Scale Down Apps

Scale each app to 0 before importing its database to prevent writes during migration.

```bash
# For teslamate
kubectl scale deployment teslamate -n default --replicas=0
flux suspend helmrelease teslamate -n default
```

### Step 2: Create New Cluster with Import

Create `kubernetes/main/apps/database/cloudnative-pg/clusters/teslamate-pg/cluster.yaml`:

```yaml
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: teslamate-pg
  namespace: database
spec:
  instances: 1
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
        host: cnpg-cluster-rw.database.svc.cluster.local
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

In `kubernetes/main/apps/default/teslamate/app/helmrelease.yaml`, change:
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

Create `kubernetes/main/apps/database/cloudnative-pg/clusters/teslamate-pg/scheduledbackup.yaml`:

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
kubernetes/main/apps/database/cloudnative-pg/
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
| teslamate-pg | 10Gi | 100 | 128MB |
| paperless-pg | 5Gi | 50 | 64MB |
| authentik-pg | 5Gi | 100 | 64MB |

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

For each migrated app:
- [ ] App connects successfully to new cluster
- [ ] Data integrity verified (spot check records)
- [ ] Scheduled backup runs successfully
- [ ] Backup appears in R2 bucket under new serverName
- [ ] App functionality tested (login, create record, etc.)

## Dependencies

- CloudNativePG operator 1.20+ (import feature)
- Source cluster must remain running during import
- Sufficient Longhorn storage for new clusters

## k3s Compatibility

Fully compatible - no k3s-specific considerations.

## Estimated Downtime

Per app:
- ~5-10 minutes for small databases (paperless, authentik)
- ~10-20 minutes for teslamate (depends on data size)

Apps can be migrated one at a time to minimize overall impact.
