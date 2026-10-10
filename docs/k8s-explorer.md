# Kubernetes repository explorer

Apollo serves the read-only MCP API for [k8s-at-home-explorer](https://github.com/evanmoelter/k8s-at-home-explorer)
at `https://explorer.${SECRET_DOMAIN}/mcp`. The route is LAN-only, uses the existing wildcard TLS
certificate, and requires the application's bearer token. There is no public route or browser SSO redirect.
The API rejects unauthenticated MCP requests; its health endpoints intentionally need no token.

## Agent connection

Configure a Streamable HTTP MCP server with the endpoint above and an `Authorization: Bearer <token>`
header. The token is `EXPLORER_API_TOKEN` in the operator-managed `hcc-apollo/k8s-explorer` item.
Supply it through the client's secret environment or credential store, never committed configuration.
Clients need LAN connectivity and DNS for the internal Gateway; an Internet-hosted client cannot reach
this LAN-only endpoint. The service's source tools return guarded commit/hash/line evidence.

The same 1Password item contains `EXPLORER_EMBEDDING_API_KEY` for Voyage and `RESTIC_PASSWORD` for
corpus backups. CNPG generates the separate database credentials. ESO mounts only application keys
into the appropriate containers; the initializer receives database access only.

## Serving and ingestion

The API, schema initializer, and hourly worker use the same digest-pinned image. The reusable upstream
app-template values and Voyage overlay are copied under the app directory; HCC owns image, credentials,
storage, routing, and catalogue overrides. API and worker use `voyage-4` at 1,024 dimensions. The worker
refreshes the tested 20-repository catalogue with two fetch workers. GitHub metadata refresh is disabled;
stars/preferences come from Git. Adding repositories requires editing the catalogue explicitly.

One pod shares an RWO corpus claim and uses Recreate updates. During initial verification, the app and
serving-check Job are pinned to hcc8 so both can mount the claim. Required post-deployment cleanup
removes the check and then the app's pin, allowing the volume to attach on another node.
Each repository publishes its latest completed scan. Failed refreshes retain the prior published source;
semantic failures preserve
completed embedding batches for the next sync. Inspect worker failure counts and index readiness:
`/health/ready` verifies database/schema access, not complete embeddings. Provider requests incur
ongoing usage; account spending controls remain the operator's responsibility.

Initial deployment is gated by two real-provider integration tests in a disposable PostgreSQL/pgvector
sidecar. A separate, fixed-identity serving-check Job waits for 20 complete semantic indexes, repeats
sync and verifies zero new embeddings for unchanged repositories, then runs the upstream
`deploy:smoke` task's underlying command, `k8s-explorer check-serving --min-ready-repositories 20`,
against the authenticated LAN HTTPS endpoint. Credentials remain inside Secret-backed containers.
Results live under `/data/deployment-check-v1/`; Job logs contain non-secret summaries. Jobs have no
automatic retries or TTL cleanup. Retrying a failed serving check requires a new Job and output identity.
The check waits up to two hours for indexing, allowing an hourly worker retry after an initial failure;
the Job allows another 30 minutes for repeat sync and smoke, and Flux waits up to 155 minutes.
These Jobs and their deployment dependencies are temporary: after checks and initial backups pass,
export the results and retire the Jobs through the required cleanup in the
[deployment plan](../plans/20261010-explorer-service.md#required-post-deployment-cleanup). Steady-state
reconciliation and recovery must not depend on rerunning paid provider tests.

For an independently configured client environment, the upstream task is:

```sh
mise run deploy:smoke -- --min-ready-repositories 20
```

Supply `EXPLORER_SMOKE_URL` and `EXPLORER_SMOKE_TOKEN` privately. Run while ingestion is idle so a
refresh cannot invalidate source guards during the check.

## Persistence and recovery

The corpus and dedicated PostgreSQL database each use retained Longhorn storage. The CNPG standard
image includes pgvector; first-install bootstrap enables the extension before application migrations.
Barman supplies weekly base backups and continuous WAL to Apollo's database bucket. VolSync snapshots
the corpus daily into the separate Apollo file-backup bucket, using the shared schedule without a manual
trigger override. The database is distinct from all disposable provider-evaluation databases, and their
cached embeddings are not imported.

These are separate backup streams, not an atomic snapshot. Restore both with ingestion stopped, verify
source guards, and rebuild derived indexes if the recovered corpus and database disagree. Catalogue and
preferences remain in Git. Follow the database and VolSync recovery lifecycles; never expect a database
restore alone to reconstruct files. After successful serving checks and both initial offsite backups,
remove first-install database init configuration together with its pgvector bootstrap patch, and retire
the one-time Jobs and fixed-node placement as specified in the deployment cleanup.

The [deployment record](../plans/20261010-explorer-service.md) retains validation and application issues.
The earlier [provider calibration](k8s-explorer-evaluation.md) documents the model selection evidence.
