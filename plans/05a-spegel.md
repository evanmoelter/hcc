# Plan: Add Spegel (P2P Container Image Distribution)

## Overview

Add Spegel to enable peer-to-peer container image distribution between nodes, reducing external registry bandwidth and improving pull times for commonly used images.

## What is Spegel?

Spegel is a stateless cluster-local OCI registry mirror that allows nodes to share container images with each other. When a node needs to pull an image that another node already has, it can pull from the local node instead of the external registry.

## Current State

- Each node pulls images independently from external registries
- No local image caching/sharing between nodes
- Higher bandwidth usage for common images

## Target State

- Spegel deployed as a DaemonSet
- Nodes share container images via P2P
- Reduced external registry bandwidth
- Faster image pulls for cached images

## Implementation Steps

### Step 1: Create Spegel namespace/app structure

Create `kubernetes/main/apps/kube-system/spegel/`:

**app/ocirepository.yaml:**
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: spegel
spec:
  interval: 1h
  url: oci://ghcr.io/spegel-org/helm-charts/spegel
  ref:
    tag: 0.6.0
```

**app/helmrelease.yaml:**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: spegel
spec:
  chartRef:
    kind: OCIRepository
    name: spegel
  interval: 1h
  values:
    spegel:
      # k3s uses containerd
      containerdSock: /run/k3s/containerd/containerd.sock
      containerdRegistryConfigPath: /var/lib/rancher/k3s/agent/etc/containerd/certs.d
    service:
      registry:
        hostPort: 29999
    serviceMonitor:
      enabled: true
```

**app/kustomization.yaml:**
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: kube-system
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
  name: spegel
  namespace: flux-system
spec:
  interval: 1h
  path: ./kubernetes/main/apps/kube-system/spegel/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  dependsOn:
    - name: cilium  # Ensure CNI is ready first
```

### Step 2: Update kube-system kustomization

Add spegel to `kubernetes/main/apps/kube-system/kustomization.yaml`:

```yaml
resources:
  - ./namespace.yaml
  - ./cilium/ks.yaml
  - ./kube-vip/ks.yaml
  - ./metrics-server/ks.yaml
  - ./reloader/ks.yaml
  - ./spegel/ks.yaml  # Add this line
```

### Step 3: Verify containerd paths for k3s

The containerd socket and registry config paths are different for k3s:

| Setting | Talos | k3s |
|---------|-------|-----|
| containerdSock | `/run/containerd/containerd.sock` | `/run/k3s/containerd/containerd.sock` |
| containerdRegistryConfigPath | `/etc/cri/conf.d/hosts` | `/var/lib/rancher/k3s/agent/etc/containerd/certs.d` |

### Step 4: Optional - Configure which registries to mirror

By default, Spegel mirrors all registries. You can customize:

```yaml
spegel:
  containerdMirrorAdd: true
  registries:
    - https://ghcr.io
    - https://docker.io
    - https://quay.io
    - https://gcr.io
```

## k3s Compatibility

✅ **Fully compatible** - Spegel works with k3s, but requires k3s-specific containerd paths.

**k3s-specific configuration:**
- Socket: `/run/k3s/containerd/containerd.sock`
- Registry config: `/var/lib/rancher/k3s/agent/etc/containerd/certs.d`

## Benefits

- **Bandwidth savings**: Images only downloaded once from external registries
- **Faster pulls**: Local P2P transfer is faster than internet download
- **Resilience**: Can pull images even if external registry is slow/down
- **Cost savings**: Reduced egress costs if using cloud registries

## When to Skip

Consider skipping Spegel if:
- You only have a single node
- Your cluster has very few shared images
- You have a local registry mirror already

## Dependencies

- Requires containerd runtime (k3s uses containerd ✅)
- Should deploy after CNI (Cilium) is ready

## Estimated Effort

~1 hour

## Testing

1. Deploy Spegel and verify DaemonSet is running on all nodes
2. Check logs: `kubectl -n kube-system logs -l app.kubernetes.io/name=spegel`
3. Pull an image on one node, then check if it's served locally on another node
4. Monitor registry traffic to verify bandwidth savings
5. Check ServiceMonitor metrics in Prometheus

