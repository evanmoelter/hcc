# Plan: Add Cloudflare DNS (External DNS for Cloudflare)

## Overview

Add external-dns with Cloudflare provider to automatically manage DNS records for services exposed via Gateway/Ingress.

## Current State

- DNS records managed manually in Cloudflare dashboard
- No automatic DNS record creation for new services
- Cloudflare tunnel handles external access but DNS is manual

## Target State

- external-dns automatically creates/updates Cloudflare DNS records
- DNS records synced from Kubernetes resources (Gateway, Ingress, DNSEndpoint)
- Records cleaned up when services are removed

## Implementation Steps

### Step 1: Create external-dns structure

Create `kubernetes/main/apps/network/cloudflare-dns/`:

**app/ocirepository.yaml:**
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: external-dns
spec:
  interval: 1h
  url: oci://registry-1.docker.io/bitnamicharts/external-dns
  ref:
    tag: 8.10.4
```

**app/helmrelease.yaml:**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: cloudflare-dns
spec:
  chartRef:
    kind: OCIRepository
    name: external-dns
  interval: 1h
  values:
    fullnameOverride: cloudflare-dns
    provider:
      name: cloudflare
    env:
      - name: CF_API_TOKEN
        valueFrom:
          secretKeyRef:
            name: cloudflare-dns-secret
            key: cloudflare-api-token
    extraArgs:
      - --cloudflare-dns-records-per-page=1000
      - --cloudflare-proxied
      - --crd-source-apiversion=externaldns.k8s.io/v1alpha1
      - --crd-source-kind=DNSEndpoint
      - --events
      - --ignore-ingress-tls-spec
    sources:
      - crd
      - gateway-httproute
      - gateway-grpcroute
      - gateway-tlsroute
      - gateway-tcproute
      - gateway-udproute
      - ingress
    domainFilters:
      - example.com  # Replace with your domain
    policy: sync
    registry: txt
    txtOwnerId: kubernetes
    txtPrefix: k8s.
    serviceMonitor:
      enabled: true
    podAnnotations:
      secret.reloader.stakater.com/reload: cloudflare-dns-secret
```

**app/secret.sops.yaml:**
```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-dns-secret
type: Opaque
stringData:
  cloudflare-api-token: ENC[AES256_GCM,data:...,type:str]  # Your encrypted token
```

**app/kustomization.yaml:**
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: network
resources:
  - ./ocirepository.yaml
  - ./helmrelease.yaml
  - ./secret.sops.yaml
```

**ks.yaml:**
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cloudflare-dns
  namespace: flux-system
spec:
  interval: 1h
  path: ./kubernetes/main/apps/network/cloudflare-dns/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  dependsOn:
    - name: external-dns-crds  # If using DNSEndpoint CRD
```

### Step 2: Create Cloudflare API Token

1. Go to Cloudflare Dashboard → Profile → API Tokens
2. Create Token with permissions:
   - Zone → DNS → Edit
   - Zone → Zone → Read
3. Limit to specific zones (your domain)
4. Encrypt the token with SOPS:

```bash
sops --encrypt --in-place kubernetes/main/apps/network/cloudflare-dns/app/secret.sops.yaml
```

### Step 3: Using DNSEndpoint CRD (Optional)

For explicit DNS records, you can use DNSEndpoint resources:

```yaml
---
apiVersion: externaldns.k8s.io/v1alpha1
kind: DNSEndpoint
metadata:
  name: my-service
  namespace: default
spec:
  endpoints:
    - dnsName: myservice.example.com
      recordType: A
      targets:
        - 192.168.1.100
      recordTTL: 300
```

### Step 4: Annotation-based DNS

For Gateway API or Ingress resources, add annotations:

```yaml
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/hostname: myapp.example.com
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
```

### Step 5: Update network kustomization

Add to `kubernetes/main/apps/network/kustomization.yaml`:

```yaml
resources:
  - ./namespace.yaml
  - ./cloudflared/ks.yaml
  - ./cloudflare-dns/ks.yaml  # Add this
  # ... other resources
```

## k3s Compatibility

✅ **Fully compatible** - external-dns is cluster-agnostic and works with any Kubernetes distribution.

## Benefits

- Automatic DNS record management
- DNS records in sync with cluster state
- Cleanup when services are removed
- Supports multiple sources (Gateway, Ingress, CRD)
- Cloudflare proxy support for DDoS protection

## Configuration Options

| Option | Description |
|--------|-------------|
| `policy: sync` | Creates, updates, AND deletes records |
| `policy: upsert-only` | Creates and updates, never deletes |
| `txtOwnerId` | Identifies records managed by this instance |
| `cloudflare-proxied` | Enable Cloudflare proxy (orange cloud) |

## Dependencies

- Cloudflare account with API token
- Domain managed in Cloudflare
- SOPS for secret encryption

## Estimated Effort

~1-2 hours

## Testing

1. Deploy external-dns and verify pod is running
2. Check logs: `kubectl -n network logs -l app.kubernetes.io/name=cloudflare-dns`
3. Create a test DNSEndpoint and verify record appears in Cloudflare
4. Create a Gateway/Ingress with annotation and verify DNS record
5. Delete resources and verify DNS records are cleaned up

