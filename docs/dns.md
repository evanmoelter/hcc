# Apollo DNS and tunnel

Apollo uses split-horizon DNS: public requests pass through Cloudflare; LAN requests reach Envoy directly.
Household hostnames stay on `main` until their individual cutovers.

| Owner | Responsibility |
|---|---|
| Terraform | Local `apollo` tunnel and proxied `external-apollo.${SECRET_DOMAIN}` alias to its UUID |
| Cloudflare external-dns | External Gateway app records pointing to that alias; owner `apollo`, `upsert-only` through Wave 1 |
| UniFi external-dns | Both Gateways’ LAN records and annotated LoadBalancer Services; owner `apollo-unifi`, `sync` |

Cloudflare reads `external-dns-cloudflare.kubernetes.io/target` on the external Gateway. UniFi uses the
`external-dns.alpha.kubernetes.io/` prefix and reads Gateway status addresses instead. Annotate raw
LoadBalancer Services with that prefix’s `hostname` key for LAN DNS. Terraform’s alias is excluded from external-dns.

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
| `external-dns-cloudflare` | `CF_API_TOKEN` | Zone DNS Edit and Zone Read, restricted to the hosted zone |
| `external-dns-unifi` | `UNIFI_API_KEY` | Local UniFi Integration API key |

ESO derives the tunnel ID from that JSON; no UUID needs copying into Git. Credential rotation currently
requires pod replacement; reloader is not installed. Allow HCC → `192.168.4.1:443` per
[networking.md](./networking.md). The UniFi webhook currently skips controller TLS verification.

## Verify after deployment

The [LAN baseline](./gateway.md#lan-verification) passed. DNS and tunnel verification remain pending:

- Confirm Flux, ExternalSecrets, both DNS deployments, two tunnel replicas, and their metrics targets are healthy.
- For `echo-apollo.${SECRET_DOMAIN}`, UniFi DNS should answer `192.168.21.101`; public DNS should answer Cloudflare addresses.
- Test HTTPS from a LAN client and an external connection. A LAN request alone does not prove the tunnel works.
- Follow the [ingress plan](../plans/04-envoy-gateway.md) for client-IP and spoofed-header checks before enabling proxy trust.

Echo is intentionally public during testing. Afterward, move its route to `envoy-internal`: LAN DNS should
change to `192.168.21.100`, and the tunnel must stop serving echo. Remove its leftover public DNS and matching
Apollo TXT record manually; `upsert-only` retains them. Tailscale access follows its operator deployment.
