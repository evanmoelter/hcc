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
Independent off-LAN verification subsequently passed; origin forged-header verification remains pending
after the trust change deploys.

The operator subsequently chose a tunnel-only external Gateway. Its NetworkPolicy admits cloudflared to
the external HTTPS listener and Prometheus to metrics. The deployed policy passed the
[isolation gate](../docs/gateway.md#external-isolation-gate) on 2026-09-17, including direct LAN and pod denial,
cross-namespace label isolation, both tunnel replicas' origin traffic, and healthy metrics. The operator
also confirmed independent off-LAN echo access. External-only pod-CIDR trust is now configured. This separates
enforcement verification from trust activation; Flux readiness cannot establish Cilium datapath enforcement.

## Remaining work

1. After the trust change deploys, verify normal and forged-header tunnel requests against Envoy's detected
   client address in access logs, following [the verification procedure](../docs/gateway.md#client-ip-verification).
   The internal Gateway must remain untrusted. Recheck tunnel isolation and metrics health. A Cloudflare 403
   without an origin request does not establish correct origin handling.
2. After client-IP verification, disable echo's external route. LAN DNS already points only to
   `192.168.21.100`; the former external-Gateway record is absent. The operator chose unauthenticated public access
   during testing; afterward disable echo's chart-generated external route, retain `echo-server-internal`,
   and verify echo is unreachable through the tunnel.
   The Tailscale operator and echo Ingress are defined;
   complete the credential setup and tailnet verification in [docs/tailscale.md](../docs/tailscale.md).
3. Before configuring Authentik or Home Assistant, complete the client-IP checks above and each app's own
   proxy-trust checks. External-only
   `ClientTrafficPolicy.spec.clientIPDetection.xForwardedFor.trustedCIDRs` uses Apollo's pod CIDR.
   Live inspection confirmed cloudflared uses the shared per-node pod ranges; individual pod addresses
   cannot survive rescheduling. The network policy provides the workload restriction that CIDR trust alone lacks.
   Keep the internal Gateway untrusted. Use Envoy's detected client address in access logs for the external path.
   The original-IP extension may omit `x-envoy-external-address` and does not sanitize every forwarded header.
   Each Gateway now has one `ClientTrafficPolicy` with a shared Kustomize patch for TLS settings;
   forwarded-header trust is configured only on the external policy. Overlapping policies do not merge automatically.
   Shared app security policies should target both routes when their requirements match. Verify the rendered
   common fields and intentional trust differences before deployment.
4. Migrate app routes during their individual cutovers. Raw LoadBalancer services and Tailscale Ingresses
   retain their separate paths. Remove ingress-nginx with the old cluster in Wave 2.

Custom error pages, additional traffic tuning, and uptime-discovery annotations are optional follow-ups.
