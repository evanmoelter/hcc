# Plan: CoreDNS as Helm Release

## Overview

Manage CoreDNS as a Flux HelmRelease instead of relying on the k3s built-in CoreDNS deployment. This provides better control over configuration and updates.

## Current State

- k3s deploys CoreDNS automatically as part of cluster bootstrap
- Configuration managed via k3s flags or manual kubectl edits
- Updates tied to k3s version

## Target State

- CoreDNS managed as a HelmRelease
- Configuration versioned in Git
- Independent update cycle from k3s
- ServiceMonitor for Prometheus metrics

## Implementation Steps

### Step 1: Disable k3s built-in CoreDNS

When installing k3s, add the `--disable coredns` flag:

```bash
# In your k3s installation script or ansible
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable coredns" sh -
```

Or update existing cluster by adding to `/etc/rancher/k3s/config.yaml`:
```yaml
disable:
  - coredns
```

**⚠️ Warning:** Disabling CoreDNS on an existing cluster will cause DNS outage until the Helm-managed version is deployed.

### Step 2: Create CoreDNS HelmRelease

Create `kubernetes/main/apps/kube-system/coredns/`:

**app/ocirepository.yaml:**
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: coredns
spec:
  interval: 1h
  url: oci://ghcr.io/coredns/charts/coredns
  ref:
    tag: 1.45.0
```

**app/helmrelease.yaml:**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: coredns
spec:
  chartRef:
    kind: OCIRepository
    name: coredns
  interval: 1h
  values:
    fullnameOverride: coredns
    image:
      repository: coredns/coredns
    k8sAppLabelOverride: kube-dns
    serviceAccount:
      create: true
    service:
      name: kube-dns
      clusterIP: "10.43.0.10"  # Match your k3s service CIDR
    replicaCount: 2
    servers:
      - zones:
          - zone: .
            scheme: dns://
            use_tcp: true
        port: 53
        plugins:
          - name: errors
          - name: health
            configBlock: |-
              lameduck 5s
          - name: ready
          - name: kubernetes
            parameters: cluster.local in-addr.arpa ip6.arpa
            configBlock: |-
              pods verified
              fallthrough in-addr.arpa ip6.arpa
          - name: autopath
            parameters: "@kubernetes"
          - name: forward
            parameters: . /etc/resolv.conf
          - name: cache
            configBlock: |-
              prefetch 20
              serve_stale
          - name: loop
          - name: reload
          - name: loadbalance
          - name: prometheus
            parameters: 0.0.0.0:9153
          - name: log
            configBlock: |-
              class error
    affinity:
      nodeAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          nodeSelectorTerms:
            - matchExpressions:
                - key: node-role.kubernetes.io/control-plane
                  operator: Exists
    tolerations:
      - key: CriticalAddonsOnly
        operator: Exists
      - key: node-role.kubernetes.io/control-plane
        operator: Exists
        effect: NoSchedule
    prometheus:
      service:
        enabled: true
      monitor:
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
  name: coredns
  namespace: flux-system
spec:
  interval: 1h
  path: ./kubernetes/main/apps/kube-system/coredns/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  dependsOn:
    - name: cilium
```

### Step 3: Update kube-system kustomization

Add coredns to `kubernetes/main/apps/kube-system/kustomization.yaml`.

### Step 4: Important Configuration Notes

**ClusterIP must match k3s DNS:**
- Default k3s service CIDR: `10.43.0.0/16`
- Default CoreDNS ClusterIP: `10.43.0.10`
- Verify with: `kubectl get svc -n kube-system kube-dns`

**Node affinity:**
- CoreDNS should run on control-plane nodes for reliability
- Tolerations needed for control-plane taints

## k3s Compatibility

⚠️ **Requires configuration change** - Must disable k3s built-in CoreDNS.

**Migration path for existing cluster:**
1. Deploy Helm-managed CoreDNS first (with different service name temporarily)
2. Verify it works
3. Update k3s to disable built-in CoreDNS
4. Update Helm release to use `kube-dns` service name

## Benefits

- GitOps-managed DNS configuration
- Independent update cycle
- Better observability with ServiceMonitor
- Consistent with rest of cluster management

## When to Skip

Consider keeping k3s built-in CoreDNS if:
- You don't need custom CoreDNS configuration
- You want simpler k3s management
- DNS is working fine as-is

## Dependencies

- Should deploy after CNI (Cilium) is ready
- May need to coordinate with k3s configuration changes

## Estimated Effort

~2-3 hours (including careful migration)

## Risks

- DNS outage during migration if not done carefully
- ClusterIP mismatch can break cluster DNS
- Misconfiguration can cause all DNS resolution to fail

## Testing

1. Verify CoreDNS pods are running: `kubectl -n kube-system get pods -l app.kubernetes.io/name=coredns`
2. Test DNS resolution: `kubectl run test --rm -it --image=busybox -- nslookup kubernetes.default`
3. Test external DNS: `kubectl run test --rm -it --image=busybox -- nslookup google.com`
4. Check metrics in Prometheus

