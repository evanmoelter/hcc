# Plan: Apollo ingress migration

The Envoy Gateway foundation is defined under `kubernetes/apollo/apps/network/`.
[docs/gateway.md](../docs/gateway.md) records its Gateways, production certificate, proxy configuration,
and the successful LAN verification on 2026-09-11. [docs/dns.md](../docs/dns.md) records the Cloudflare and
UniFi controllers, locally managed Apollo tunnel, split-horizon mechanism, and deployment checks.
Household apps still use ingress-nginx on `main`.

## Working decision

On 2026-09-16, the operator chose separate internal and external HTTPRoutes for public apps, preserving
one hostname and backend. This is a soft decision, favoring explicit separation and future policy flexibility.
Revisit it if duplication, DNS coordination, or policy maintenance causes significant pain; the single-route
alternative remains available. The [migration design](./20260816-talos-migration.md#dns-and-ingress)
records the comparison and shared-policy approach.

On 2026-09-17 UTC, the dual routes passed LAN DNS, TLS, redirect, and forged-header checks; requests forced
to public DNS addresses also reached Apollo through the tunnel. The verification records preserve those
results in [gateway.md](../docs/gateway.md#lan-verification) and [dns.md](../docs/dns.md#verify-after-deployment).
Independent off-LAN and origin forged-header verification remain pending.

The operator subsequently chose a tunnel-only external Gateway. Its NetworkPolicy admits cloudflared to
the external listeners and Prometheus to metrics. Forwarded-header trust stays disabled until the deployed
policy passes the [isolation gate](../docs/gateway.md#external-isolation-gate). This separates enforcement
verification from trust activation; Flux readiness cannot establish Cilium datapath enforcement.

## Remaining work

1. Verify the tunnel-only policy on new connections from the LAN and non-cloudflared pods, including a
   cloudflared-labeled pod in another namespace. Confirm both tunnel replicas, proxy readiness, and metrics
   remain healthy. Temporary probe pods require operator approval.
2. Complete independent off-LAN testing of echo-server's external route. LAN DNS already points only to
   `192.168.21.100`; the former external-Gateway record is absent. The operator chose unauthenticated public access
   during testing; afterward disable echo's chart-generated external route, retain `echo-server-internal`,
   and verify echo is unreachable through the tunnel.
   The Tailscale operator and echo Ingress are defined;
   complete the credential setup and tailnet verification in [docs/tailscale.md](../docs/tailscale.md).
3. After isolation passes, enable external-only
   `ClientTrafficPolicy.spec.clientIPDetection.xForwardedFor.trustedCIDRs` for Apollo's pod CIDR.
   Live inspection confirmed cloudflared uses the shared per-node pod ranges; individual pod addresses
   cannot survive rescheduling. The network policy provides the workload restriction that CIDR trust alone lacks.
   Keep the internal Gateway untrusted. Verify forged headers on both paths before configuring Authentik or
   Home Assistant, using Envoy's detected client address in access logs for the external path. The original-IP
   extension may omit `x-envoy-external-address` and does not sanitize every forwarded header.
   Each Gateway now has one `ClientTrafficPolicy` with a shared Kustomize patch for TLS settings;
   forwarded-header trust remains unset. Overlapping policies do not merge automatically. Shared app security
   policies should target both routes when their requirements match. Verify the rendered common fields and
   intentional trust differences before deployment.
4. Migrate app routes during their individual cutovers. Raw LoadBalancer services and Tailscale Ingresses
   retain their separate paths. Remove ingress-nginx with the old cluster in Wave 2.

Custom error pages, additional traffic tuning, and uptime-discovery annotations are optional follow-ups.
