# Apollo DNS and tunnel

Apollo uses separate Cloudflare and UniFi external-dns instances in `network`, plus a locally managed
Cloudflare tunnel. Household hostnames remain on `main` until their individual cutovers.

## Record ownership

Terraform owns the tunnel and the fixed proxied CNAME `external-apollo.${SECRET_DOMAIN}` pointing to
`<tunnel UUID>.cfargotunnel.com`. Cloudflare external-dns explicitly excludes that name and manages only
app hostnames. Terraform has no UniFi provider or connection; the UniFi webhook handles LAN records.

| Controller | Sources | Records | Owner | Policy |
|---|---|---|---|---|
| `external-dns-cloudflare` | External Gateway HTTPRoutes | Proxied CNAMEs to `external-apollo.${SECRET_DOMAIN}` | `apollo` | `upsert-only` |
| `external-dns-unifi` | Both Gateways' HTTPRoutes, annotated LoadBalancer Services | LAN A records | `apollo-unifi` | `sync` |

Cloudflare reads annotations under `external-dns-cloudflare.kubernetes.io/`; UniFi reads
`external-dns.alpha.kubernetes.io/`. The external Gateway declares its tunnel target only under the
Cloudflare prefix. UniFi therefore uses the Gateway's status address, `192.168.21.101`. An internal-only
route uses `192.168.21.100` and is outside the Cloudflare controller's Gateway scope. The HTTP redirect
route excludes itself from both controllers. Distinct TXT prefixes separate ownership from the old cluster.

Raw LoadBalancer Services opt into UniFi with an `external-dns.alpha.kubernetes.io/hostname` annotation.
They are excluded from public discovery so a LAN Service address is never published through Cloudflare.
The two Gateway Services have no hostname annotation; the HTTPRoutes supply app names.

During testing, echo has one parent, `envoy-external`. A LAN lookup should produce only `192.168.21.101`;
an external lookup should reach Cloudflare. This tests the planned split-horizon shape with one canonical
hostname. [The ingress plan](../plans/04-envoy-gateway.md) tracks its acceptance and the dual-route fallback.

## Tunnel and credentials

[`terraform/cloudflare`](../terraform/cloudflare/) manages the locally configured `apollo` tunnel and fixed
alias alongside the existing R2 buckets. The provider reads its management token from `CLOUDFLARE_API_TOKEN`;
it needs Account Cloudflare Tunnel Edit, Zone DNS Edit, and Zone Read for the relevant account and zone.
The operator supplies `TF_VAR_apollo_zone_id` for the zone matching Apollo's `SECRET_DOMAIN`, plus
`TF_VAR_apollo_tunnel_secret` with a base64-encoded secret containing at least 32 random bytes.
Keep that input in 1Password and reuse it for future runs. The existing SOPS datasource supplies the
Cloudflare account ID and R2 provider credentials. The R2 backend setup is described in `main.tf`.

Terraform planning and applying are operator steps because this stack decrypts its SOPS datasource.
Review the plan before applying, including the existing bucket resources. The Cloudflare provider stores
the tunnel secret in remote state; `sensitive` hides it from ordinary output but does not encrypt it.
Keep saved plans and state out of git. Terraform is pinned in Mise. After supplying the backend credentials
and inputs in the environment, the operator runs:

```sh
mise exec -- terraform -chdir=terraform/cloudflare init
mise exec -- terraform -chdir=terraform/cloudflare plan
mise exec -- terraform -chdir=terraform/cloudflare apply
```

After applying, `apollo_tunnel_alias` must match `external-apollo.${SECRET_DOMAIN}`.
`apollo_tunnel_id` identifies the tunnel, and the sensitive `apollo_tunnel_credentials`
output contains the complete connector credentials JSON. Transfer it directly to 1Password without
posting it in chat or committing it. The runtime connector gets only this tunnel's credentials; its
Secret does not contain the account management token. ESO extracts `TunnelID` from the JSON into the
connector's `TUNNEL_ID` environment variable, so no tunnel UUID needs to be copied into Git or Flux variables.

Create these items in the `hcc-apollo` vault:

| Item | Field | Value |
|---|---|---|
| `cloudflared` | `credentials.json` | Complete JSON from the Terraform credentials output |
| `external-dns-cloudflare` | `CF_API_TOKEN` | Zone DNS Edit and Zone Read, restricted to the hosted zone |
| `external-dns-unifi` | `UNIFI_API_KEY` | Local UCG Fiber Integration API key |

ESO reads these fields through the `onepassword` ClusterSecretStore. Both DNS controllers depend on that
store, monitoring, and the Gateway configuration. The tunnel has the same prerequisites. ConfigMap changes
roll its two replicas through a chart-generated checksum. Secret changes require replacement pods to
reload credentials; Apollo does not yet run reloader.

Allow HCC to reach `192.168.4.1:443` as described in [networking.md](./networking.md). UniFi's webhook uses
the local Integration API and the `default` site. It currently follows the webhook's self-signed-controller
setting, `UNIFI_SKIP_TLS_VERIFY=true`; traffic is encrypted but the controller certificate is not verified.
Set a trusted controller CA and disable that option when certificate validation is configured.

The tunnel's HelmRelease holds its ingress configuration. Wildcard requests go to
`https://envoy-external.network.svc.cluster.local:443`, preserving Host and verifying origin TLS against
`external-apollo.${SECRET_DOMAIN}`. The final rule returns 404. No tunnel path reaches the internal Gateway.
The controller, webhook, and connector have resource requests, memory limits, hardened UID/GID 568 contexts,
and Prometheus ServiceMonitors.

## Verification and cleanup

The [LAN baseline](./gateway.md#lan-verification) passed on 2026-09-11. DNS publication, tunnel connectivity,
split-horizon behavior, and the new metrics targets still require verification after deployment.

```sh
flux --context apollo get kustomizations -A
kubectl --context apollo -n network get helmrelease,externalsecret,deployment
kubectl --context apollo -n network get gateway,httproute
kubectl --context apollo -n network get pods -o wide
```

Expect both DNS deployments and two cloudflared replicas to be Ready, all three ExternalSecrets to report
Ready, and echo to be Accepted with ResolvedRefs on the external Gateway. Confirm Prometheus has healthy
targets for the DNS controllers and tunnel.

Set `gateway_test_host` to the actual echo hostname without reading Kubernetes Secrets:

```sh
gateway_test_host='echo-apollo.YOUR_DOMAIN'
dig @192.168.4.1 "$gateway_test_host" A
dig @1.1.1.1 "$gateway_test_host" A
curl --noproxy '*' --fail --silent --show-error "https://${gateway_test_host}/"
```

The UniFi answer must be `192.168.21.101`; the public answer must contain Cloudflare addresses. Test HTTPS
from both a LAN client using UniFi DNS and an external connection, with certificate verification enabled.
Do not follow a public DNS lookup with an ordinary LAN curl and assume that proves the tunnel: curl uses
the workstation's resolver. Use an external connection or `--resolve` with an address from the public lookup.
Confirm existing household app records and the old tunnel still work.

The operator chose public unauthenticated echo access for this test. Compare ordinary requests and requests
with forged `X-Forwarded-For: 198.51.100.123` and `CF-Connecting-IP: 198.51.100.123` headers on both paths.
Forwarded-header trust is initially disabled on both Gateways. LAN requests must preserve the real client
address; tunnel requests identify the connector peer until trust is configured. Record that peer and compare
it with cloudflared's pod addresses before selecting narrow `trustedCIDRs`. Do not trust all pods or nodes,
use `numTrustedHops` alone, or configure app trusted proxies before the spoofing tests pass with the final
policy. If source identity cannot be kept narrow through pod replacement, settle an isolated tunnel path
before enabling trust. The internal Gateway remains untrusted.

When testing finishes, change echo's parent from `envoy-external` to `envoy-internal` in its HelmRelease and
let Flux converge. UniFi should then answer `192.168.21.100`, LAN HTTPS should still work, and a request
through the tunnel must no longer return echo data. Cloudflare's `upsert-only` policy leaves the obsolete
public record behind; the operator can remove that record and its matching Apollo TXT ownership record
after confirming the external route is gone. Keep `upsert-only` through Wave 1. Tailscale access can be added
after Apollo's separate Tailscale operator is deployed.

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
