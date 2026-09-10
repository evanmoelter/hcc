# Apollo certificates

Cert-manager runs in `security`. Before deployment, create a dedicated Cloudflare token with
`Zone: DNS: Edit` and `Zone: Zone: Read`, restricted to the zone named by `${SECRET_DOMAIN}`.
Store it in `hcc-apollo` → `cert-manager` → `CLOUDFLARE_DNS_TOKEN`; ESO creates `cert-manager-secret`.
ESO polls hourly, with possible provider delays. During rotation, retain the old token until the
replacement has synced and successfully issued a certificate.

The `wildcard` Certificate in `network` requests the apex and wildcard from the production issuer.
Both Envoy Gateways use its `wildcard` TLS Secret in the same namespace. The certificate has its own
Flux Kustomization, `envoy-gateway-certificates`, depending on `cert-manager-issuers`; gateway configuration
waits for certificate readiness. Production issuance and LAN verification remain pending.
Check readiness after deployment:

```sh
kubectl --context apollo -n security get externalsecret cert-manager
kubectl --context apollo get clusterissuers
kubectl --context apollo -n network get certificate wildcard
kubectl --context apollo -n network get orders,challenges
```

A Ready issuer proves account registration; a Ready Certificate proves DNS-01 issuance.
The staging test Certificate is removed from git. Cert-manager retains its Secret after Certificate
deletion; any cleanup of that leftover Secret requires operator approval. Keep the staging issuer for
future issuance testing. [docs/gateway.md](./gateway.md) covers TLS verification without changing DNS.

## References

The OCI chart, public DNS self-checks, and ServiceMonitor pattern follow
[onedr0p](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml),
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/cert-manager/cert-manager.yaml),
[szinn](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/apps/cert-manager/cert-manager/app/helmrelease.yaml),
and [joryirving](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/cert-manager/cert-manager/helmrelease.yaml).
Separate issuer reconciliation also appears in
[Mafyuh's layout](https://github.com/Mafyuh/iac/blob/main/kubernetes/cluster/cert-manager/ks.yaml).

Upstream documents [Cloudflare permissions](https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/)
and the [staging environment](https://letsencrypt.org/docs/staging-environment/).
