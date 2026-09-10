# Apollo certificates

Apollo runs cert-manager in the `cert-manager` namespace. Its OCI Helm chart installs the CRDs,
controller, CA injector, and two webhook replicas. A ServiceMonitor feeds the bootstrap Prometheus.
Webhook scheduling prefers separate nodes, while allowing co-location when necessary.
The controller uses public Cloudflare DNS-over-HTTPS resolvers for DNS-01 self-checks, independently
of the LAN's split-horizon answers.

The Flux Kustomizations separate four readiness gates:

- `cert-manager` installs the chart after `kube-prometheus-stack`.
- `cert-manager-secrets` waits for `onepassword-store` and the ExternalSecret's Ready condition.
- `cert-manager-issuers` waits for the controller and credential, then for both ClusterIssuers to be Ready.
- `cert-manager-certificates` waits for the issuers, then for the staging certificate to be Ready.

Platform components that need cert-manager's API, such as Barman, depend on `cert-manager`.
They do not need to wait for public certificate issuance.

## Operator setup

Create a dedicated Cloudflare API token for Apollo's cert-manager with `Zone: DNS: Edit` and
`Zone: Zone: Read`, restricted to the zone named by `${SECRET_DOMAIN}`. In the `hcc-apollo` vault,
create an item titled `cert-manager` with a field labeled `CLOUDFLARE_DNS_TOKEN` containing that token.
ESO reads it into `cert-manager-secret` in the `cert-manager` namespace. Keep the token separate from
the old cluster and from external-dns. No credential belongs in git.

ESO polls the credential hourly. Provider synchronization or reconciliation failures can delay an
update further. When rotating the token, keep the old token valid until the replacement has synced
and certificate issuance succeeds with it.

The `letsencrypt-staging` and `letsencrypt-production` ClusterIssuers create separate ACME account
keys in Apollo. These are independent of the old cluster's accounts. Apollo deliberately omits the
optional ACME contact email.

## Staging test and Gateway handoff

`wildcard-staging` requests the domain apex and wildcard from Let's Encrypt staging and stores the
result in the `wildcard-staging` Secret. Staging certificates are not browser-trusted. The test
exercises ESO, Cloudflare permissions, DNS validation, issuance, and renewal without requesting a
production certificate or changing application routing.

Staging still creates temporary TXT records in the real Cloudflare zone. Both clusters can have
challenge values at the same name; cert-manager's Cloudflare solver cleans up its matching value.
The old cluster continues serving its own production certificate.

After deployment, inspect readiness without reading Secrets:

```sh
kubectl --context apollo -n flux-system get kustomizations
kubectl --context apollo -n cert-manager get externalsecret cert-manager
kubectl --context apollo get clusterissuers
kubectl --context apollo -n cert-manager get certificate wildcard-staging
kubectl --context apollo -n cert-manager get orders,challenges
```

A Ready issuer proves account registration, but only a Ready Certificate proves the DNS-01 path.
Deployment and issuance still need to be verified on the live cluster.

During the Gateway work, create the production Certificate in the Gateways' namespace and reference
its Secret from their listeners. Remove the staging Certificate and its Flux registration after the
test is no longer needed. By default, cert-manager leaves certificate Secrets behind when a Certificate is removed;
the operator must separately approve deletion of the leftover `wildcard-staging` Secret. Coordinate
initial production issuance with the old cluster as described in the migration plan.

## References

The OCI chart, public DNS self-checks, and ServiceMonitor pattern follow
[onedr0p](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/cert-manager/cert-manager/app/helmrelease.yaml),
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/cert-manager/cert-manager.yaml),
[szinn](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/apps/cert-manager/cert-manager/app/helmrelease.yaml),
and [joryirving](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/cert-manager/cert-manager/helmrelease.yaml).
Separate issuer reconciliation also appears in
[Mafyuh's layout](https://github.com/Mafyuh/iac/blob/main/kubernetes/cluster/cert-manager/ks.yaml).
Apollo keeps the default ACME certificate profile and begins with a staging test.

Upstream documents [Cloudflare permissions](https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/)
and the [staging environment](https://letsencrypt.org/docs/staging-environment/).
