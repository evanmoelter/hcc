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
records the comparison and shared-policy approach. This decision does not establish deployment or verification.

## Remaining work

1. Complete the operator credential and firewall setup in the DNS runbook and verify Flux readiness.
2. Verify echo-server's separate internal and external HTTPRoutes with the same hostname and backend.
   UniFi's Gateway source is scoped to `envoy-internal`, with its annotated Service source retained;
   Cloudflare remains scoped to `envoy-external`. Verify LAN DNS points only to `192.168.21.100` and public
   DNS reaches the tunnel. Confirm UniFi removes the former external-Gateway LAN record.
   Provider-specific annotation prefixes now let Cloudflare read the external Gateway's tunnel target
   while UniFi reads the internal Gateway's LAN status address. The operator chose unauthenticated public access
   during testing; afterward disable echo's chart-generated external route, retain `echo-server-internal`,
   and verify echo is unreachable through the tunnel.
   The Tailscale operator and echo Ingress are defined;
   complete the credential setup and tailnet verification in [docs/tailscale.md](../docs/tailscale.md).
3. Establish cloudflared's actual source address and the narrowest justified forwarded-header trust.
   Use `ClientTrafficPolicy.spec.clientIPDetection.xForwardedFor.trustedCIDRs` to bind trust to those proxy ranges.
   Keep the internal Gateway untrusted. Do not enable `numTrustedHops` alone on a Gateway reachable
   directly from the LAN. Verify forged headers on both paths before configuring Authentik or Home Assistant.
   Each Gateway now has one `ClientTrafficPolicy` with a shared Kustomize patch for TLS settings;
   forwarded-header trust remains unset. Overlapping policies do not merge automatically. Shared app security
   policies should target both routes when their requirements match. Verify the rendered common fields and
   intentional trust differences before deployment.
4. Migrate app routes during their individual cutovers. Raw LoadBalancer services and Tailscale Ingresses
   retain their separate paths. Remove ingress-nginx with the old cluster in Wave 2.

Custom error pages, additional traffic tuning, and uptime-discovery annotations are optional follow-ups.
