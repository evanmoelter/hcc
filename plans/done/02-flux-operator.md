# Plan: Flux Operator Instead of Traditional Flux

## Overview

Migrate from traditional Flux bootstrap to the Flux Operator approach with **zero downtime**, following the [official migration guide](https://fluxoperator.dev/docs/guides/migration/).

## Current State

- Flux v2.4.0 bootstrapped via `kubernetes/main/bootstrap/flux/kustomization.yaml`
- Self-managed via OCIRepository (`oci://ghcr.io/fluxcd/flux-manifests:v2.4.0`)
- GitRepository `home-kubernetes` pointing to `https://github.com/evanmoelter/hcc`
- Existing customizations in `kubernetes/main/flux/config/flux.yaml`:
  - Network policies disabled (k3s compatibility)
  - Concurrent workers: 8
  - Kube API QPS: 500, Burst: 1000
  - Requeue dependency: 5s
  - Memory limits: 2Gi, CPU: 2000m
  - Helm OOM detection enabled

## Target State

- Flux managed via Flux Operator + FluxInstance CRD
- Centralized configuration with all customizations in FluxInstance
- Automated operator upgrades via HelmRelease
- Better observability with ServiceMonitor

## Implementation Steps

### Step 1: Install Flux Operator

Install the Flux Operator in the same namespace as existing Flux. This can be done initially via Helm CLI, then managed via GitOps afterward.

**Manual installation (one-time):**
```bash
helm install flux-operator oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator \
  --namespace flux-system
```

### Step 2: Create FluxInstance Resource

Create the FluxInstance CRD that matches the current bootstrap configuration. The operator will take over management of existing Flux components.

**Create `kubernetes/main/apps/flux-system/flux-instance/app/fluxinstance.yaml`:**
```yaml
---
apiVersion: fluxcd.controlplane.io/v1
kind: FluxInstance
metadata:
  name: flux
  namespace: flux-system
spec:
  distribution:
    version: "2.4.x"
    registry: "ghcr.io/fluxcd"
  components:
    - source-controller
    - kustomize-controller
    - helm-controller
    - notification-controller
  cluster:
    type: kubernetes
    multitenant: false
    networkPolicy: false  # k3s compatibility
    domain: "cluster.local"
  sync:
    kind: GitRepository
    url: "https://github.com/evanmoelter/hcc.git"
    ref: "refs/heads/main"
    path: "kubernetes/main/flux"
  kustomize:
    patches:
      # Increase the number of reconciliations and API limits
      - patch: |
          - op: add
            path: /spec/template/spec/containers/0/args/-
            value: --concurrent=8
          - op: add
            path: /spec/template/spec/containers/0/args/-
            value: --kube-api-qps=500
          - op: add
            path: /spec/template/spec/containers/0/args/-
            value: --kube-api-burst=1000
          - op: add
            path: /spec/template/spec/containers/0/args/-
            value: --requeue-dependency=5s
        target:
          kind: Deployment
          name: (kustomize-controller|helm-controller|source-controller)
      # Increase resource limits
      - patch: |
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: not-used
          spec:
            template:
              spec:
                containers:
                  - name: manager
                    resources:
                      limits:
                        cpu: 2000m
                        memory: 2Gi
        target:
          kind: Deployment
          name: (kustomize-controller|helm-controller|source-controller)
      # Enable Helm OOM detection
      - patch: |
          - op: add
            path: /spec/template/spec/containers/0/args/-
            value: --feature-gates=OOMWatch=true
          - op: add
            path: /spec/template/spec/containers/0/args/-
            value: --oom-watch-memory-threshold=95
          - op: add
            path: /spec/template/spec/containers/0/args/-
            value: --oom-watch-interval=500ms
        target:
          kind: Deployment
          name: helm-controller
```

### Step 3: Apply FluxInstance and Verify

```bash
kubectl apply -f kubernetes/main/apps/flux-system/flux-instance/app/fluxinstance.yaml
```

**Verify the operator has taken over:**
```bash
# Check FluxInstance status
kubectl -n flux-system get fluxinstance flux

# Verify Flux no longer manages itself (expected: "Not managed by Flux")
flux trace kustomization flux-system
```

### Step 4: Clean Up Old Flux Configuration

Once the migration is verified, remove the old self-management configuration from the repository:

1. Remove `kubernetes/main/flux/config/flux.yaml` (the old OCIRepository + Kustomization for Flux self-management)
2. Keep `kubernetes/main/flux/config/cluster.yaml` (GitRepository and cluster Kustomization - these will be managed by FluxInstance)

**Note:** The FluxInstance's `sync` configuration replaces the GitRepository and Kustomization in `cluster.yaml`. After migration, you may need to update how the cluster Kustomization is handled.

### Step 5: Add GitOps Management for Flux Operator

Create the GitOps resources to manage the Flux Operator via HelmRelease:

**Create `kubernetes/main/apps/flux-system/flux-operator/`:**

**app/ocirepository.yaml:**
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: flux-operator
spec:
  interval: 1h
  url: oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator
  ref:
    tag: 0.16.0
  layerSelector:
    mediaType: "application/vnd.cncf.helm.chart.content.v1.tar+gzip"
    operation: copy
```

**app/helmrelease.yaml:**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: flux-operator
spec:
  interval: 1h
  releaseName: flux-operator
  chartRef:
    kind: OCIRepository
    name: flux-operator
  values:
    resources:
      limits:
        cpu: 500m
        memory: 256Mi
      requests:
        cpu: 100m
        memory: 64Mi
```

**app/kustomization.yaml:**
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: flux-system
resources:
  - ./ocirepository.yaml
  - ./helmrelease.yaml
```

**ks.yaml:**
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: flux-operator
  namespace: flux-system
spec:
  interval: 1h
  path: ./kubernetes/main/apps/flux-system/flux-operator/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
```

### Step 6: Add FluxInstance to GitOps

**Create `kubernetes/main/apps/flux-system/flux-instance/`:**

**app/kustomization.yaml:**
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: flux-system
resources:
  - ./fluxinstance.yaml
```

**ks.yaml:**
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: flux-instance
  namespace: flux-system
spec:
  dependsOn:
    - name: flux-operator
  interval: 1h
  path: ./kubernetes/main/apps/flux-system/flux-instance/app
  prune: false  # Don't prune FluxInstance to avoid breaking Flux
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
```

### Step 7: Update flux-system Kustomization

Update `kubernetes/main/apps/flux-system/kustomization.yaml`:
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./namespace.yaml
  - ./flux-operator/ks.yaml
  - ./flux-instance/ks.yaml
  - ./webhooks/ks.yaml
  - ./capacitor/ks.yaml
```

## k3s Compatibility

✅ **Fully compatible** - Flux Operator works with any Kubernetes distribution including k3s. Network policies are disabled in the FluxInstance configuration.

## Benefits

- **Zero-downtime migration** - Operator takes over existing Flux components seamlessly
- Centralized Flux configuration via FluxInstance CRD
- Performance optimizations preserved from existing setup
- Easier upgrades via Renovate (just update OCIRepository tags)
- Better observability with ServiceMonitor
- GitOps-native Flux deployment

## Migration Verification Checklist

1. [ ] Flux Operator pod is running in flux-system namespace
2. [ ] FluxInstance shows Ready status
3. [ ] `flux trace kustomization flux-system` shows "Not managed by Flux"
4. [ ] All existing Kustomizations continue to reconcile
5. [ ] All existing HelmReleases continue to reconcile
6. [ ] GitRepository `home-kubernetes` is syncing correctly

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Operator fails to take over | Keep old flux.yaml until migration is verified |
| Customization patches incompatible | Test patches in FluxInstance match current behavior |
| Sync issues after migration | Verify GitRepository and Kustomization paths |

## Rollback Plan

If migration fails:
1. Delete the FluxInstance: `kubectl delete fluxinstance flux -n flux-system`
2. Uninstall Flux Operator: `helm uninstall flux-operator -n flux-system`
3. Re-apply bootstrap: `kubectl apply -k kubernetes/main/bootstrap/flux`

## Testing

1. Verify Flux Operator pod is running
2. Apply FluxInstance and check status is Ready
3. Verify all controllers are running with expected configuration
4. Test GitRepository sync
5. Verify HelmReleases and Kustomizations reconcile
6. Check pod resource limits match expected values
