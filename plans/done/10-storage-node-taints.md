# Plan: Dedicated Storage Nodes with Taints

## Overview

Taint the underpowered nodes `hcc` and `hcc2` so only Longhorn storage replicas run on them, keeping compute workloads on the more powerful nodes.

## Current State

- Nodes `hcc` and `hcc2` have the most storage capacity but are underpowered with loud fans
- Longhorn is deployed with 3 replicas and `defaultDataLocality: best-effort`
- All nodes currently accept all workloads

## Target State

- `hcc` and `hcc2` are tainted to reject non-storage workloads
- Longhorn tolerates the taint and schedules replicas on these nodes
- With `defaultDataLocality: best-effort`, one replica stays local to the workload, and the other 2 replicas land on the tainted storage nodes
- Compute workloads only run on the more powerful nodes

## Implementation Steps

### Step 1: Label the Nodes

Add labels to identify these as storage-dedicated nodes:

```bash
kubectl label nodes hcc hcc2 node-role.kubernetes.io/storage=true
```

### Step 2: Taint the Nodes

Apply the taint to prevent non-storage workloads:

```bash
kubectl taint nodes hcc hcc2 dedicated=storage:NoSchedule
```

### Step 3: Update Longhorn HelmRelease

Update `kubernetes/main/apps/storage/longhorn/app/helmrelease.yaml` to add taint toleration:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: longhorn
spec:
  interval: 30m
  timeout: 15m
  chart:
    spec:
      chart: longhorn
      version: 1.6.4
      sourceRef:
        kind: HelmRepository
        name: longhorn
        namespace: flux-system
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
  values:
    persistence:
      enabled: true
      defaultClassReplicaCount: 3
      defaultDataLocality: best-effort
    defaultSettings:
      defaultReplicaCount: 3
      defaultDataPath: /storage01
      defaultDataLocality: best-effort
      replicaAutoBalance: best-effort
      taintToleration: "dedicated=storage:NoSchedule"
    ingress:
      enabled: true
      ingressClassName: internal
      host: longhorn.${SECRET_DOMAIN}
      tls: true
```

### Step 4: Verify Configuration

After Flux reconciles, verify:

```bash
# Check nodes have the taint
kubectl describe nodes hcc hcc2 | grep -A5 Taints

# Check Longhorn settings
kubectl -n longhorn-system get settings taint-toleration -o yaml

# Verify Longhorn pods can run on tainted nodes
kubectl -n longhorn-system get pods -o wide

# Check replica distribution
kubectl -n longhorn-system get replicas -o wide
```

### Step 5: Test Workload Scheduling

Verify non-storage pods are not scheduled on tainted nodes:

```bash
# Should show no application pods on hcc/hcc2
kubectl get pods -A -o wide | grep -E "^(hcc|hcc2)"
```

## How It Works

With this configuration:

1. **Normal pods** cannot schedule on `hcc`/`hcc2` (no toleration)
2. **Longhorn instance-manager and replica pods** can schedule anywhere (they have the toleration)
3. **Data locality** ensures one replica stays on the node running the workload
4. **Remaining replicas** naturally land on `hcc`/`hcc2` since other nodes are busier with compute

## Node Configuration (Manual Steps)

The node labels and taints must be applied manually or via your node provisioning system. These are not managed by GitOps:

```bash
# Run once per node
kubectl label nodes hcc hcc2 node-role.kubernetes.io/storage=true
kubectl taint nodes hcc hcc2 dedicated=storage:NoSchedule
```

If using Talos or another declarative node config, add these to the machine configuration instead.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Existing pods on hcc/hcc2 get evicted | Taints only affect new scheduling; existing pods continue running |
| Longhorn can't schedule replicas | Verify `taintToleration` setting is applied before tainting nodes |
| Not enough replica targets | Ensure at least 3 nodes total (1 compute + 2 storage) for 3 replicas |

## Rollback Plan

If issues occur:

```bash
# Remove taints
kubectl taint nodes hcc hcc2 dedicated=storage:NoSchedule-

# Optionally remove labels
kubectl label nodes hcc hcc2 node-role.kubernetes.io/storage-
```

Then remove `taintToleration` from the Longhorn HelmRelease.

## Verification Checklist

1. [ ] Nodes `hcc` and `hcc2` are labeled with `node-role.kubernetes.io/storage=true`
2. [ ] Nodes `hcc` and `hcc2` have taint `dedicated=storage:NoSchedule`
3. [ ] Longhorn setting `taint-toleration` shows `dedicated=storage:NoSchedule`
4. [ ] Longhorn replica pods can run on tainted nodes
5. [ ] New application pods do not schedule on tainted nodes
6. [ ] Volume replicas are distributed across all nodes including tainted ones
