# Apollo DNS and tunnel

Apollo uses split-horizon DNS: public requests pass through Cloudflare; LAN requests reach Envoy directly.
Household hostnames stay on `main` until their individual cutovers.

| Owner | Responsibility |
|---|---|
| Terraform | Local `apollo` tunnel and proxied `external-apollo.${SECRET_DOMAIN}` alias to its UUID |
| `cloudflare-dns` | External Gateway app records pointing to that alias; owner `apollo`, `upsert-only` through Wave 1 |
| `unifi-dns` | Internal Gateway LAN records and annotated LoadBalancer Services; owner `apollo-unifi`, `sync` |

Cloudflare reads `external-dns-cloudflare.kubernetes.io/target` on the external Gateway. UniFi uses the
`external-dns.alpha.kubernetes.io/` prefix and reads Gateway status addresses instead. Annotate raw
LoadBalancer Services with that prefix’s `hostname` key for LAN DNS. Terraform’s alias is excluded from external-dns.

Public apps with LAN access use separate HTTPRoutes on the internal and external Gateways with the same
hostname and backend. UniFi's Gateway filter prevents it from publishing both Gateway addresses for that name.
The filter leaves its LoadBalancer Service source enabled. External-only routes, such as the Flux webhook,
do not create UniFi records; local clients use public DNS for those names.
The external Gateway accepts HTTPS only from cloudflared. Direct LAN requests use the internal Gateway;
the [external isolation gate](./gateway.md#external-isolation-gate) passed before external-only forwarded-header trust
was configured.

Both DNS releases use the signed [OCI mirror](https://github.com/home-operations/charts-mirror).
Move to upstream OCI when available; the mirror prunes charts six months afterward.

## Operator setup

Run `init`, review `plan`, then `apply` in [terraform/cloudflare](../terraform/cloudflare/) using Mise.
Supply the existing R2 backend credentials and these environment variables:

- `CLOUDFLARE_API_TOKEN`: Account Cloudflare Tunnel Edit, Zone DNS Edit, and Zone Read.
- `TF_VAR_apollo_zone_id`: zone matching Apollo’s `SECRET_DOMAIN`.
- `TF_VAR_apollo_tunnel_secret`: base64-encoded secret containing at least 32 random bytes; retain it in 1Password.

This stack decrypts its existing SOPS datasource, so planning and applying are operator steps.
The tunnel secret is stored in remote Terraform state. Copy the sensitive `apollo_tunnel_credentials`
output into the `hcc-apollo` vault:

| 1Password item | Field | Value |
|---|---|---|
| `cloudflared` | `credentials.json` | Terraform credentials output |
| `cloudflare-dns` | `CF_API_TOKEN` | Zone DNS Edit and Zone Read, restricted to the hosted zone |
| `unifi-dns` | `UNIFI_API_KEY` | Local UniFi Integration API key |

ESO derives the tunnel ID from that JSON; no UUID needs copying into Git. Both DNS deployments and cloudflared
opt into [Reloader](./secrets.md#configuration-reloads), so changes to their referenced Secrets trigger rollouts.
Allow HCC → `192.168.4.1:443` per
[networking.md](./networking.md). The UniFi webhook currently skips controller TLS verification.

## Verify after deployment

The [LAN and dual-route checks](./gateway.md#lan-verification) passed. On 2026-09-17 UTC, UniFi DNS at
`192.168.4.1` and `192.168.20.1`, and the workstation resolver, returned only `192.168.21.100` for echo;
the previous external-Gateway address was absent. Public DNS returned Cloudflare addresses. Requests from
the LAN forced to those public addresses reached Apollo through the tunnel with valid TLS and HTTP 200.
Envoy still identified cloudflared's pod as the client. A public request carrying forged X-Forwarded-For
and CF-Connecting-IP headers returned Cloudflare HTTP 403, so that request did not verify origin handling.
On 2026-09-17, the operator independently confirmed off-LAN echo access. The tunnel-only isolation checks
passed, both cloudflared replicas had successful origin requests after policy deployment, and the tunnel
and proxy metrics targets were healthy. After external-only trust deployed, normal and forged-XFF requests
identified the real public client in origin logs. Cloudflare rejected forged CF-Connecting-IP requests
before the origin; [the verification record](./gateway.md#client-ip-verification) preserves that limitation
and the separate requirement for app proxy-header checks.

For deployment checks and later changes:

- Confirm Flux, ExternalSecrets, both DNS deployments, two tunnel replicas, and their metrics targets are healthy.
- For `echo-apollo.${SECRET_DOMAIN}`, UniFi DNS should answer only `192.168.21.100`; public DNS should answer Cloudflare addresses.
- Confirm the former echo LAN address `192.168.21.101` is removed, not retained alongside the internal address.
- Test HTTPS from a LAN client and an external connection. A LAN request alone does not prove the tunnel works.
- Complete [client-IP and spoofed-header checks](./gateway.md#client-ip-verification) before configuring app proxy trust.
- Verify direct LAN access to the external Gateway is blocked while public tunnel requests and proxy metrics succeed.

Echo remains intentionally public throughout the cluster migration for further testing. After the migration
is complete, first replace Gatus's probe target and verify alert delivery as described in the
[Gateway cleanup prerequisite](./gateway.md#client-ip-verification).
Then disable echo's chart-generated external route and retain `echo-server-internal`: LAN DNS should
remain `192.168.21.100`, and the tunnel must stop serving echo. Then verify removal of the public
`echo-apollo.${SECRET_DOMAIN}` CNAME and its matching
`k8s.apollo.cloudflare.cname-echo-apollo.${SECRET_DOMAIN}` TXT record. If external-dns still uses `upsert-only`,
remove them manually after confirming Apollo ownership; after Wave 2 restores `sync`, check automatic cleanup.
Keep both records until route removal. [Tailscale](./tailscale.md) has a separate echo Ingress whose HTTPS
path was also verified on 2026-09-17.

## References

The provider separation follows [onedr0p](https://github.com/onedr0p/home-ops/tree/main/kubernetes/apps/network),
[szinn](https://github.com/szinn/k8s-homelab/tree/main/kubernetes/main/apps/network/external-dns),
[joryirving](https://github.com/joryirving/home-ops/tree/main/kubernetes/apps/base/network/cloudflare-dns),
[Mafyuh](https://github.com/Mafyuh/iac/tree/main/kubernetes/oke/cluster/cloudflare-dns), and
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/kube-system/external-dns/external-dns-cloudflare.yaml).
Apollo uses [ExternalDNS's configurable annotation prefix](https://github.com/kubernetes-sigs/external-dns/blob/v0.22.0/source/annotations/annotations.go)
to produce direct LAN A records instead of a private alias chain. The
[UniFi webhook](https://github.com/home-operations/external-dns-unifi-webhook) documents API setup;
[Cloudflare's tunnel resource](https://github.com/cloudflare/terraform-provider-cloudflare/blob/v5.24.0/docs/resources/zero_trust_tunnel_cloudflared.md)
and [local configuration](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)
describe tunnel ownership and connector configuration.
