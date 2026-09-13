# Apollo databases

The Barman plugin must share the CNPG operator's namespace for service discovery and mutual TLS.
Keep the upstream chart's service and certificate names; they are part of that integration.
See the [upstream requirements](https://cloudnative-pg.io/plugin-barman-cloud/docs/installation/).

Each app's Cluster and ObjectStore belong in the app's namespace. Give the database its own Flux
Kustomization, depending on `plugin-barman-cloud` and `longhorn-config`, and gate the app on database
readiness. Health checks cannot order resources applied by the same Kustomization.

Deployment readiness, Barman certificate issuance, and the operator's Prometheus scrape remain unverified.
A healthy plugin does not prove recovery: the first physical restore must verify that it can read the
old cluster's in-tree Barman archive.

[Storage](storage.md#r2-backup-separation) records backup bucket separation.
The [migration plan](../plans/20260816-talos-migration.md) tracks the reusable Postgres component and per-app cutovers.
