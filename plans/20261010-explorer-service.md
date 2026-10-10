# Persistent explorer service

Deploy the upstream service at the operator-pinned image digest using the reusable app-template
values and Voyage overlay from source revision `5eed2805d945094dcc5ae13e3a9ee2fdfcbcd445`.
Keep all cluster configuration here. The evaluation plan concerns disposable databases and is
not the serving architecture.

## Decisions

- Operator: Voyage `voyage-4`, 1,024 dimensions, tested 20-repository catalogue.
- Operator: LAN-only HTTPS at `explorer.${SECRET_DOMAIN}/mcp`, native bearer authentication.
- Dedicated `k8s-explorer` application in `default`; one API/worker pod with Recreate updates.
- Dedicated PostgreSQL 17 standard CNPG image includes pgvector. Initialize the extension in the
  application database as part of CNPG bootstrap; the application uses its generated owner role.
- New 10 GiB Longhorn corpus PVC and 10 GiB database, with existing VolSync and Barman R2 backups.
  Disk capacity and platform readiness checked before provisioning. Retain durable claims.
- ESO item `hcc-apollo/k8s-explorer`: `EXPLORER_API_TOKEN`, `EXPLORER_EMBEDDING_API_KEY`,
  `RESTIC_PASSWORD`; operator confirmation pending. No agent reads of credential values.
- Disable GitHub metadata refresh initially, use catalogue metadata and two fetch workers.
  Refresh configured repositories hourly; discovery remains explicit.

## Deployment order

1. ESO credentials, then a one-shot real-provider validation Job using the exact application image,
   checksum-verified upstream test files and locked test dependencies. PostgreSQL is a pod-loopback
   native sidecar backed only by emptyDir. Require both selected tests to pass without skips.
2. Only after validation succeeds, provision corpus storage and a dedicated CNPG database, then
   the API/worker release and LAN route. No public route or Authentik browser redirect.
3. Observe initial worker ingestion. Run a GitOps validation Job after all 20 selected repositories
   are ready: repeat sync, record cache reuse, and execute the deployment smoke against LAN HTTPS.
   Keep keys inside Secret-backed containers. Export non-secret reports and logs locally.
4. Verify both offsite backup streams, then remove first-install database initialization settings.
   Keep validation results and document endpoint/client setup, recovery limitations, and app issues.

Database and corpus backups are separate streams, not an atomic snapshot. Recover both with the worker
stopped, verify source guards, and rebuild derived indexes if their snapshots do not match. Catalogue
and preferences remain in Git. Never substitute the old evaluation database for the serving database.

## Sources

- [Upstream handoff](https://github.com/evanmoelter/k8s-at-home-explorer/blob/5eed2805d945094dcc5ae13e3a9ee2fdfcbcd445/docs/deployment.md)
- [CNPG standard images](https://github.com/cloudnative-pg/postgres-containers#standard-images)
- [Community operator example](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/cnpg-system/cloudnative-pg/app/helmrelease.yaml)
- Apollo database, storage, secrets, gateway and DNS docs govern the cluster integration.

## Execution record

Pending deployment and verification.
