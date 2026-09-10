# Apollo certificates

Cert-manager runs in `security`. Before deployment, create a dedicated Cloudflare token with
`Zone: DNS: Edit` and `Zone: Zone: Read`, restricted to the zone named by `${SECRET_DOMAIN}`.
Store it in `hcc-apollo` → `cert-manager` → `CLOUDFLARE_DNS_TOKEN`; ESO creates `cert-manager-secret`.
ESO polls hourly, with possible provider delays. During rotation, retain the old token until the
replacement has synced and successfully issued a certificate.

`wildcard-staging` tests DNS-01 issuance for the apex and wildcard. Its certificate is not browser-trusted.
Check readiness after deployment:

```sh
kubectl --context apollo -n security get externalsecret cert-manager
kubectl --context apollo get clusterissuers
kubectl --context apollo -n security get certificate wildcard-staging
kubectl --context apollo -n security get orders,challenges
```

A Ready issuer proves account registration; a Ready Certificate proves DNS-01 issuance.
Gateway work will request the production certificate in the Gateways' namespace and remove the staging
test. Cert-manager retains the staging Secret after Certificate deletion; deleting that leftover Secret
requires operator approval.

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
