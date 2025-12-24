# Plan: Envoy Gateway (Replacing ingress-nginx)

## Overview

Consider migrating from ingress-nginx to Envoy Gateway, which implements the modern Kubernetes Gateway API. This provides a more flexible and feature-rich ingress solution.

## Current State

- Using ingress-nginx for cluster ingress
- Ingress resources defined using `networking.k8s.io/v1 Ingress`
- External access via Cloudflare tunnel to ingress-nginx

## Target State

- Envoy Gateway as the ingress controller
- HTTPRoute resources for routing (Gateway API)
- Separate internal and external gateways
- Better integration with cert-manager for TLS

## Implementation Steps

### Step 1: Deploy Envoy Gateway

Create `kubernetes/main/apps/network/envoy-gateway/`:

**app/ocirepository.yaml:**
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: envoy-gateway
spec:
  interval: 1h
  url: oci://docker.io/envoyproxy/gateway-helm
  ref:
    tag: v1.3.0
```

**app/helmrelease.yaml:**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: envoy-gateway
spec:
  chartRef:
    kind: OCIRepository
    name: envoy-gateway
  interval: 1h
  values:
    config:
      envoyGateway:
        provider:
          type: Kubernetes
          kubernetes:
            deploy:
              type: GatewayNamespace
```

### Step 2: Create GatewayClass

**app/gatewayclass.yaml:**
```yaml
---
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: envoy
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller
```

### Step 3: Create Internal Gateway

**app/gateway-internal.yaml:**
```yaml
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: envoy-internal
  namespace: network
  annotations:
    # For Cilium L2 announcements
    io.cilium/lb-ipam-ips: "192.168.1.100"  # Your internal LB IP
spec:
  gatewayClassName: envoy
  listeners:
    - name: http
      protocol: HTTP
      port: 80
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - name: wildcard-cert
            namespace: cert-manager
```

### Step 4: Create External Gateway (for Cloudflare Tunnel)

**app/gateway-external.yaml:**
```yaml
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: envoy-external
  namespace: network
  annotations:
    io.cilium/lb-ipam-ips: "192.168.1.101"  # Your external LB IP
spec:
  gatewayClassName: envoy
  listeners:
    - name: http
      protocol: HTTP
      port: 80
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - name: wildcard-cert
            namespace: cert-manager
```

### Step 5: Migrate Ingress to HTTPRoute

**Before (Ingress):**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
spec:
  ingressClassName: nginx
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app
                port:
                  number: 80
```

**After (HTTPRoute):**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
spec:
  parentRefs:
    - name: envoy-internal
      namespace: network
  hostnames:
    - app.example.com
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: my-app
          port: 80
```

### Step 6: Update Cloudflare Tunnel

Update cloudflared config to point to the external gateway IP instead of ingress-nginx.

### Step 7: Gradual Migration

1. Deploy Envoy Gateway alongside ingress-nginx
2. Create new HTTPRoutes for services
3. Test each service with the new gateway
4. Update DNS/tunnel to point to new gateway
5. Remove old Ingress resources
6. Remove ingress-nginx

## k3s Compatibility

✅ **Fully compatible** - Envoy Gateway works with k3s. However, there are some considerations:

- k3s Traefik can be disabled to avoid conflicts: `--disable traefik`
- LoadBalancer service IPs work with Cilium L2 or kube-vip
- Service mesh features may require additional configuration

## Benefits

- Modern Gateway API (future standard)
- Better separation of infrastructure (Gateway) and application (HTTPRoute) concerns
- Native support for traffic splitting, canary deployments
- Better observability with built-in metrics
- More flexible TLS configuration

## Risks & Considerations

⚠️ **This is a significant migration** that affects all ingress traffic.

- All Ingress resources need to be converted to HTTPRoute
- Cloudflare tunnel configuration needs updating
- May have different behavior for some edge cases
- Learning curve for Gateway API

## Alternative: Keep ingress-nginx

If the migration seems too risky, you can:
- Keep ingress-nginx
- Optionally add Gateway API CRDs for future use
- Migrate gradually as you add new services

## Dependencies

- Cilium with L2 announcements or kube-vip for LoadBalancer IPs
- cert-manager for TLS certificates
- May want to implement after other changes are stable

## Estimated Effort

~6-8 hours (including migration of all services)

## Testing

1. Deploy Envoy Gateway in parallel with ingress-nginx
2. Create HTTPRoutes for a test service
3. Verify routing works correctly
4. Test TLS termination
5. Test with Cloudflare tunnel
6. Load test to compare performance

