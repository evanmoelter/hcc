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

## Settled configuration from reference repos

Steps 1 through 7 predate the Talos decision and sketch the shape. This section records the details four community repos have converged on, and answers questions `plans/20260816-talos-migration.md` leaves open. Apply it to Apollo; the k3s notes below are historical.

### Client address on both paths

The migration plan needs the real client address on the LAN path and Cloudflare's forwarded headers on the tunnel path, because Authentik's trusted-proxy configuration and Home Assistant's proxy CIDRs depend on which one a request took.

`externalTrafficPolicy: Local` on the Envoy service, set through the `EnvoyProxy` resource, is required either way. Without it the LAN path is source-NATed by kube-proxy replacement and every client looks like a node. It preserves the connection address and settles nothing about forwarded headers.

Forwarded headers are the harder half, and **`numTrustedHops` alone is not safe here**. It takes the client IP from the Nth address from the right of `X-Forwarded-For` and does not check who sent it, so a client reaching a Gateway directly can supply any `X-Forwarded-For` it likes and choose its own apparent address. On a Gateway that serves both cloudflared and the LAN, that is a spoofable input feeding Authentik's trusted-proxy decision.

Bind the trust to the sender instead. Envoy Gateway's `xForwardedFor` accepts `trustedCIDRs` as an alternative to `numTrustedHops`, which is the setting that expresses "believe this header only from cloudflared". Resolve, before Authentik moves:

- Which CIDR cloudflared actually presents to the Gateway, and whether it is narrow enough to be worth trusting.
- Whether the internal Gateway should trust `X-Forwarded-For` at all, given nothing legitimately forwards to it.

Test with a spoofed `X-Forwarded-For` from a LAN client on echo-server and confirm the address the backend sees. Getting this wrong shows up as an authentication loop, or as an access decision made on an attacker-supplied address, not as a routing error.

### One policy for both Gateways

`ClientTrafficPolicy` and `BackendTrafficPolicy` both accept `targetSelectors`, so a single policy of each kind can cover every Gateway:

```yaml
spec:
  targetSelectors:
    - group: gateway.networking.k8s.io
      kind: Gateway
```

Use this for TLS version, timeouts, compression, and retry behavior, where the two Gateways drifting apart is the failure mode.

Do not use it for client IP detection. A shared policy is what would apply one trust rule to a Gateway reached only through cloudflared and to one reached directly from the LAN, which is the hole described above. If the two paths need different trust, that setting needs its own `ClientTrafficPolicy` per Gateway even though everything else stays shared.

### Gateway configuration

- Attach an `EnvoyProxy` through the `GatewayClass` `parametersRef` rather than per Gateway. It carries replica count, resources, the service's `externalTrafficPolicy`, and Prometheus telemetry.
- Pin the Envoy LoadBalancer address with `spec.infrastructure.annotations`, using Cilium's `lbipam.cilium.io/ips`, so a Gateway's address comes from the address plan rather than from pool order.
- Put `external-dns.alpha.kubernetes.io/target` on the **Gateway**, not on each route. external-dns reads it only from Gateways, so this keeps each Gateway's target in one place instead of repeating it per route. That is what the dual-route shape wants: each Gateway carries its own target, and each instance is scoped to one Gateway.
- It does **not** deliver split-horizon. The annotation holds a single value, and every instance watching that Gateway reads the same one, so pointing it at the Cloudflare alias does not also yield the LAN address for UniFi. Route- and Gateway-scoping flags choose which Gateways an instance sees, not what target it publishes. Split-horizon therefore still needs a mechanism this plan has not identified, and the echo-server test in the migration plan has to settle that before the shape can be chosen — otherwise dual-route is the answer by default.
- Give the HTTP listeners a single redirect route rather than one per app, annotated `external-dns.alpha.kubernetes.io/controller: none` so external-dns does not publish the redirect's own hostname.

### external-dns

- Sources are `["crd", "gateway-httproute", "service"]`. The migration plan already replaces `["crd", "ingress"]`; `service` is the part worth not dropping, since Paperless's SFTP `LoadBalancer` is published that way.
- Scope ownership with both `txtOwnerId` and `txtPrefix`, for example `txtPrefix: k8s.apollo.%{record_type}-`. The plan's `txtOwnerId: apollo` alone leaves the two clusters writing TXT records at the same names; a per-cluster prefix means they cannot collide even before `policy: upsert-only` is considered. Give the UniFi instance its own prefix as well.

### Deferred

- `BackendTrafficPolicy` `responseOverride` redirecting 4xx and 5xx to a static error-page service. Nice, and unrelated to the migration.
- Per-Gateway `gatus` endpoint annotations for uptime discovery. Revisit if gatus is ever deployed.

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

