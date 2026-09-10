# Plan: Apollo ingress migration

The Envoy Gateway foundation is defined under `kubernetes/apollo/apps/network/`.
[docs/gateway.md](../docs/gateway.md) records its Gateways, production certificate, proxy configuration,
and pending LAN verification. Household apps still use ingress-nginx on `main`.

## Remaining work

1. Run the LAN checks in the gateway runbook, including TLS, redirects, and spoofed forwarded headers.
2. Create Apollo's independent Cloudflare tunnel and `external-apollo.${SECRET_DOMAIN}` alias.
   Route cloudflared to `envoy-external` with that alias as `originServerName`.
3. Deploy Cloudflare and UniFi external-dns with Gateway API sources. Retain `service` discovery for
   raw LoadBalancer services such as Paperless SFTP. Give each instance distinct `txtOwnerId` and
   `txtPrefix` values; use `policy: upsert-only` for Apollo's Cloudflare instance during migration.
4. Test the split-horizon and dual-route options in
   [the migration plan](./20260816-talos-migration.md#dns-and-ingress) using echo-server, then record the choice.
   A Gateway's external-dns target annotation supplies one target to every watcher; it does not by itself
   produce a Cloudflare alias for one provider and a LAN IP for another. Settle that mechanism before
   adopting split-horizon. The foundation's single test route attached to both Gateways is only a LAN probe.
5. Establish cloudflared's actual source address and the narrowest justified forwarded-header trust.
   Keep the internal Gateway untrusted. Do not enable `numTrustedHops` alone on a Gateway reachable
   directly from the LAN. Verify forged headers on both paths before configuring Authentik or Home Assistant.
   If trust differs per Gateway, account for Envoy Gateway's policy attachment and merge behavior rather
   than assuming that multiple `ClientTrafficPolicy` resources combine automatically.
6. Migrate app routes during their individual cutovers. Raw LoadBalancer services and Tailscale Ingresses
   retain their separate paths. Remove ingress-nginx with the old cluster in Wave 2.

Custom error pages, additional traffic tuning, and uptime-discovery annotations are optional follow-ups.
