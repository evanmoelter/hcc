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
Independent off-LAN verification subsequently passed. After external-only trust deployed, normal and
forged-XFF requests identified the real public client in origin logs. Forged CF-Connecting-IP requests were
rejected by Cloudflare before reaching Envoy, so external-origin handling of that header remains untested.
LAN forged-header checks and the Tailscale HTTPS path also passed.

The operator subsequently chose a tunnel-only external Gateway. Its NetworkPolicy admits cloudflared to
the external HTTPS listener and Prometheus to metrics. The deployed policy passed the
[isolation gate](../docs/gateway.md#external-isolation-gate) on 2026-09-17, including direct LAN and pod denial,
cross-namespace label isolation, both tunnel replicas' origin traffic, and healthy metrics. The operator
also confirmed independent off-LAN echo access. External-only pod-CIDR trust is now configured. This separates
enforcement verification from trust activation; Flux readiness cannot establish Cilium datapath enforcement.

The operator chose to keep echo publicly accessible until the cluster migration is complete, so further
testing can use the existing public, LAN, and Tailscale paths. Successful ingress checks do not trigger
public-route or DNS removal.

## Remaining work

1. Before configuring Authentik or Home Assistant, complete each app's own
   proxy-trust checks using the [Gateway trust configuration](../docs/gateway.md) as the starting point.
   The external-origin CF-Connecting-IP case remains unexercised; Cloudflare's 403 is not an origin result.
2. Migrate app routes during their individual cutovers. Raw LoadBalancer services and Tailscale Ingresses
   retain their separate paths. Remove ingress-nginx with the old cluster in Wave 2.
3. After the cluster migration is complete, disable echo's chart-generated external route, retain its
   internal and Tailscale paths, and verify echo is unreachable through the tunnel. Complete the public DNS
   cleanup in [dns.md](../docs/dns.md); keep the route and records available until then.

Custom error pages, additional traffic tuning, and uptime-discovery annotations are optional follow-ups.
