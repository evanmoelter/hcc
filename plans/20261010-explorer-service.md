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
4. Verify both offsite backup streams, then complete the required GitOps cleanup below. Deployment
   is not complete until the one-time gates are retired and steady-state reconciliation is verified.
   Keep validation results and document endpoint/client setup, recovery limitations, and app issues.

## Required post-deployment cleanup

Keep the bootstrap gates only until both provider tests, the 20-repository serving check, and the first
offsite database and corpus backups succeed. Export Job logs, `/data/deployment-check-v1/`, and backup
status before pruning their Kubernetes resources. Do not replace immutable Jobs automatically or reuse
an existing report directory: an intentional retry uses a new Job name and output directory in Git.
The serving check allows two hours for ingestion, including an hourly retry, with another 30 minutes
for repeat sync and smoke; Flux allows five additional minutes for Job completion reporting.

1. Commit the following cleanup together and let Flux converge:
   - Remove `k8s-explorer-validation` from `dependsOn` in `ks-storage.yaml` and `ks-database.yaml`.
     Preserve their storage, database platform, and secret dependencies.
   - Replace the corpus backup's `k8s-explorer-verify` dependency in `ks-storage.yaml` with
     `k8s-explorer`, retaining `volsync` and `onepassword-store`.
   - Remove `ks-validation.yaml` and `ks-verify.yaml` from the default namespace's
     `kustomization.yaml`, and delete those files and their `validation/` and `verify/` directories.
   - Remove the `k8s-explorer-initial-backup` Kustomization document from `ks-storage.yaml` and
     its `backup/` directory. Keep the shared CNPG ScheduledBackup and WAL configuration.
   - Remove the postgres `init` component from `ks-database.yaml` and the
     `/spec/bootstrap/initdb/postInitApplicationSQL` patch from `database/kustomization.yaml`
     together. Keep PostgreSQL parameter overrides; recovery restores the existing vector extension.
2. Verify Flux has pruned the one-time Jobs and their pods. Then remove the application's
   `controllers.explorer.pod.nodeSelector` override from `app/helmrelease.yaml` in a follow-up commit.
   The hcc8 pin is required only while the serving-check pod shares the RWO corpus claim; the disposable
   provider-validation Job has no node pin.
3. Run the Apollo schema, policy, and render checks for both commits. Verify the application and
   corpus backup Kustomizations reconcile without validation or verify dependencies, the API remains
   reachable with authentication, the ReplicationSource has its daily schedule and no manual trigger,
   and the database renders recovery bootstrap. Preserve the completed plan and evidence in
   `plans/done/` and update the documentation link when deployment is complete.

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
