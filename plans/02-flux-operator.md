# Plan: Flux Operator Instead of Traditional Flux

## Overview

Migrate from traditional Flux bootstrap to the Flux Operator approach, which provides better manageability, performance tunings, and GitOps-native Flux deployment.

## Current State

- Flux is bootstrapped manually or via flux CLI
- Configuration scattered across multiple files
- No centralized Flux configuration management

## Target State

- Flux managed via HelmRelease (flux-operator + flux-instance)
- Centralized configuration via FluxInstance CRD
- Pre-configured performance optimizations
- Easier upgrades through Renovate

## Implementation Steps

### Step 1: Add flux-operator HelmRelease

Create `kubernetes/main/apps/flux-system/flux-operator/`:

**app/ocirepository.yaml:**
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: flux-operator
spec:
  interval: 1h
  url: oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator
  ref:
    tag: 0.37.1
```

**app/helmrelease.yaml:**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: flux-operator
spec:
  chartRef:
    kind: OCIRepository
    name: flux-operator
  interval: 1h
  values:
    serviceMonitor:
      create: true
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

### Step 2: Add flux-instance HelmRelease

Create `kubernetes/main/apps/flux-system/flux-instance/`:

**app/helmrelease.yaml:**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: flux-instance
spec:
  chartRef:
    kind: OCIRepository
    name: flux-instance
  interval: 1h
  values:
    instance:
      distribution:
        artifact: oci://ghcr.io/controlplaneio-fluxcd/flux-operator-manifests:v0.37.1
        version: 2.x
      cluster:
        networkPolicy: false
      components:
        - source-controller
        - kustomize-controller
        - helm-controller
        - notification-controller
      sync:
        kind: GitRepository
        url: "https://github.com/<your-repo>.git"  # Update this
        ref: "refs/heads/main"
        path: kubernetes/main/flux
      commonMetadata:
        labels:
          app.kubernetes.io/name: flux
      kustomize:
        patches:
          - # Increase the number of workers
            patch: |
              - op: add
                path: /spec/template/spec/containers/0/args/-
                value: --concurrent=10
              - op: add
                path: /spec/template/spec/containers/0/args/-
                value: --requeue-dependency=5s
            target:
              kind: Deployment
              name: (kustomize-controller|helm-controller|source-controller)
          - # Increase memory limits
            patch: |
              apiVersion: apps/v1
              kind: Deployment
              metadata:
                name: all
              spec:
                template:
                  spec:
                    containers:
                      - name: manager
                        resources:
                          limits:
                            memory: 1Gi
            target:
              kind: Deployment
              name: (kustomize-controller|helm-controller|source-controller)
          - # Enable in-memory kustomize builds
            patch: |
              - op: add
                path: /spec/template/spec/containers/0/args/-
                value: --concurrent=20
              - op: replace
                path: /spec/template/spec/volumes/0
                value:
                  name: temp
                  emptyDir:
                    medium: Memory
            target:
              kind: Deployment
              name: kustomize-controller
          - # Enable Helm repositories caching
            patch: |
              - op: add
                path: /spec/template/spec/containers/0/args/-
                value: --helm-cache-max-size=10
              - op: add
                path: /spec/template/spec/containers/0/args/-
                value: --helm-cache-ttl=60m
              - op: add
                path: /spec/template/spec/containers/0/args/-
                value: --helm-cache-purge-interval=5m
            target:
              kind: Deployment
              name: source-controller
          - # Flux near OOM detection for Helm
            patch: |
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

### Step 3: Update kustomization.yaml

Add the new apps to `kubernetes/main/apps/flux-system/kustomization.yaml`.

### Step 4: Migration Strategy

This is a **breaking change** that requires careful migration:

1. **Option A: Fresh cluster** - Deploy flux-operator on a new cluster
2. **Option B: In-place migration** (risky)
   - Deploy flux-operator alongside existing flux
   - Gradually migrate workloads
   - Remove old flux components

## k3s Compatibility

✅ **Fully compatible** - Flux Operator works with any Kubernetes distribution including k3s.

## Benefits

- Centralized Flux configuration
- Performance optimizations out of the box
- Easier upgrades via Renovate
- Better observability with ServiceMonitor
- GitOps-native Flux deployment

## Dependencies

- Requires careful migration planning
- May need to coordinate with other changes

## Estimated Effort

~4-6 hours (including testing and migration)

## Risks

- Breaking change requiring migration strategy
- Potential downtime during migration
- Need to ensure all existing Flux resources are preserved

## Testing

1. Deploy on a test cluster first
2. Verify all controllers are running
3. Test GitRepository sync
4. Verify HelmReleases and Kustomizations reconcile
5. Check ServiceMonitor metrics in Prometheus

