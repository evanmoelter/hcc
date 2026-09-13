# Apollo databases

CloudNativePG and its Barman Cloud plugin run in the `database` namespace. The operator watches all
namespaces; each app's database Cluster and ObjectStore belong beside the app when it migrates.
The platform installation creates no PostgreSQL instances, backup schedules, or object-store credentials.

## Reconciliation and monitoring

The operator waits for `longhorn-config` and `kube-prometheus-stack`. The plugin has its own Flux
Kustomization, waiting for the operator and cert-manager. Future database Kustomizations should depend
on `plugin-barman-cloud` and `longhorn-config`, and wait for their Cluster to become Ready before the app starts.

The upstream plugin chart creates its own namespaced self-signed issuer and client/server certificates.
It must share the operator's namespace for service discovery and mutual TLS. Keep the chart's service
and certificate names; they are part of that integration. It does not use the public wildcard issuer.

Prometheus discovers the operator's PodMonitor. Database metrics and backup alerts belong with the
future per-app clusters. Controller images, including Barman's future database sidecar, take their
versions from the digest-pinned charts.

## Deployment verification

After Flux reconciles, inspect without reading certificate Secrets:

```sh
kubectl --context apollo -n flux-system get kustomizations cloudnative-pg plugin-barman-cloud
kubectl --context apollo -n database get helmreleases,pods
kubectl --context apollo -n database get issuers,certificates
kubectl --context apollo -n database get service barman-cloud -o yaml
kubectl --context apollo -n database get podmonitors
```

Both releases and Barman certificates must be Ready. Check the service's `cnpg.io/pluginName` label and
TLS annotations, and confirm Prometheus reports the operator scrape target as up. Deployment readiness
and scraping remain unverified until these manifests are reconciled. A healthy plugin Deployment does
not prove backup or recovery: those checks need a database, an ObjectStore, and credentials.

## App migration

The reusable Postgres component, per-app sizing and PostgreSQL versions, backup credentials, and
restore verification remain in the [migration plan](../plans/20260816-talos-migration.md).
[Storage](storage.md#r2-backup-separation) records the separate Apollo write bucket and old restore source.
The first physical recovery must prove that the plugin can read the old in-tree Barman archive before
the remaining databases move.

The official chart layout draws from
[billimek's CNPG installation](https://github.com/billimek/k8s-gitops/tree/master/kubernetes/default/cloudnative-pg/chart).
[Upstream installation requirements](https://cloudnative-pg.io/plugin-barman-cloud/docs/installation/)
describe plugin placement and cert-manager integration.
