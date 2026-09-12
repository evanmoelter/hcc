# Plan: Apollo ingress migration

The Envoy Gateway foundation is defined under `kubernetes/apollo/apps/network/`.
[docs/gateway.md](../docs/gateway.md) records its Gateways, production certificate, proxy configuration,
and the successful LAN verification on 2026-09-11. [docs/dns.md](../docs/dns.md) records the Cloudflare and
UniFi controllers, locally managed Apollo tunnel, split-horizon mechanism, and deployment checks.
Household apps still use ingress-nginx on `main`.

## Remaining work

1. Complete the operator credential and firewall setup in the DNS runbook and verify Flux readiness.
2. Test the split-horizon and dual-route options in
   [the migration plan](./20260816-talos-migration.md#dns-and-ingress) using echo-server, then record the choice.
   Provider-specific annotation prefixes now let Cloudflare read the external Gateway's tunnel target
   while UniFi reads its LAN status address. Echo attaches only to the external Gateway during this test.
   The operator chose unauthenticated public access during testing; afterward move echo to the internal
   Gateway and verify it is unreachable through the tunnel. Tailscale access follows operator installation.
3. Establish cloudflared's actual source address and the narrowest justified forwarded-header trust.
   Use `ClientTrafficPolicy.spec.clientIPDetection.xForwardedFor.trustedCIDRs` to bind trust to those proxy ranges.
   Keep the internal Gateway untrusted. Do not enable `numTrustedHops` alone on a Gateway reachable
   directly from the LAN. Verify forged headers on both paths before configuring Authentik or Home Assistant.
   If trust differs per Gateway, account for Envoy Gateway's policy attachment and merge behavior rather
   than assuming that multiple `ClientTrafficPolicy` resources combine automatically.
4. Migrate app routes during their individual cutovers. Raw LoadBalancer services and Tailscale Ingresses
   retain their separate paths. Remove ingress-nginx with the old cluster in Wave 2.

Custom error pages, additional traffic tuning, and uptime-discovery annotations are optional follow-ups.
