# Authentik migration

Prepared for review; cutover and application verification are pending. This is the next app in the
[Talos migration](20260816-talos-migration.md), after Mealie.

## Decisions

- Preserve Authentik 2025.10.3 during the move, then upgrade sequentially on Apollo after verification.
- Import the `authentik` database from shared PostgreSQL 16 into PostgreSQL 18. The pinned Authentik
  release [tests against PostgreSQL 18](https://github.com/goauthentik/authentik/blob/version/2025.10.3/.github/workflows/ci-main.yml).
- Preserve `sso.${SECRET_DOMAIN}` and the apex-domain WebFinger endpoint used for Tailscale discovery.
- Keep all source data, secrets, and the internal Ingress on `main` for rollback. There are no files or
  separately managed outposts to transfer, per the operator's earlier confirmation.

The two-PR stack is merged in order, with an explicit stop-and-backup gate between PRs:

1. **Disable on main:** turn off server/worker autoscaling, set Authentik server, worker, and WebFinger
   replicas to zero, and explicitly disable both public Ingresses. Keep the shared CNPG cluster and
   Dragonfly running for Paperless and TeslaMate.
2. **Rebuild on Apollo:** logically import only Authentik into `security/authentik-pg`, start the pinned
   Authentik release after database readiness, and expose SSO and WebFinger through the dual Gateways.
   Add the apex tunnel match and make Apollo Mealie depend on the local Authentik Kustomization.

Do not merge the stack as a unit. This document does not authorize live mutations. PR merge and any
on-demand backup are separate operator actions at the maintenance window.

## Before the maintenance window

Both PRs must pass CI and review. Read the old-cluster render: only the three replica counts, the two
HPAs, and the two public Ingresses should change. Retain `authentik-internal`, the source database,
encrypted Secret, and the old HelmReleases. WebFinger uses the upstream image on Apollo; its issuer
and subject behavior match the old fork, but verify discovery and a fresh Tailscale login at cutover.

The operator supplies these values in `hcc-apollo`; agents do not read or write them:

| Item | Fields |
|---|---|
| `authentik` | Original `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_EMAIL__USERNAME`, `AUTHENTIK_EMAIL__PASSWORD` |
| `authentik-postgres-migration` | Original `AUTHENTIK_POSTGRESQL__PASSWORD` for source role `authentik` |
| `cloudflare-r2`, `cnpg-r2` | Existing Apollo account ID and bucket-scoped backup credentials |

The original Secret also has legacy `INIT_POSTGRES_USER` and `INIT_POSTGRES_PASS` keys. Apollo does
not use the old initialization mechanism. CNPG creates new app credentials; only the temporary import
uses the source password. Preserve the exact Authentik secret key and SMTP credentials, including an
empty value if one is intentionally empty. Do not generate a new Authentik key.

Confirm the source password corresponds to the `authentik` role. The source database and its public
tables are owned by that role; its only extension is `plpgsql`. A read-only inspection found 136 MB of
data. Apollo reserves 10 GiB for the restored database and temporary logical dump; Longhorn maintains
three replicas. Confirm free capacity on each storage node before merging.

Confirm Apollo can reach `192.168.6.21:5432` through the temporary firewall rule in
[networking.md](../docs/networking.md). The source uses TLS with `sslmode: require`; its certificate
identity is not verified for the IP-based import. Source credential possession and the narrow network
path are required. Apollo application connections verify the destination CNPG CA and service hostname.

Confirm `s3://tf-hcc-apollo-cnpg/authentik/` and server name `authentik-pg-apollo-v1` are unused.
A partial previous attempt requires diagnosis, not a blind bootstrap retry. The initial import removes
the component's empty-archive bypass; it must not append to an unrelated archive.

Record representative source users, groups, applications, providers, signing-key fingerprints, and
flows for comparison without copying credentials or personal records into git. Confirm Mealie's
verified-email claim mapping still works. Include Tailscale and any other existing OIDC/SAML consumers
in the verification list. Arrange a local recovery/admin login method before disabling SSO.

## Cutover gates

### 1. Stop source writes and release public records

Merge only the disable PR. Wait for `main` Flux to apply its revision and confirm:

```sh
kubectl --context main -n security get deployments authentik-server authentik-worker webfinger
kubectl --context main -n security get pods,hpa,ingresses
kubectl --context main -n database get cluster cnpg-cluster
```

All three Deployments must have zero running pods, both Authentik HPAs must be gone, and both public
Ingresses must be gone. The internal Ingress intentionally remains but has no ready backend. Wait for
old external-dns to release both `sso.${SECRET_DOMAIN}` and the apex record and their ownership TXT
records. Existing Tailscale devices retain their identities; this migration moves login discovery,
not an operator-managed tailnet Service.

With explicit operator approval, create a final on-demand CNPG `Backup` for `database/cnpg-cluster`
using its in-tree `barmanObjectStore` method. Verify it completed after all Authentik writers stopped
and record its name and completion time below. The shared database remains live for its other apps.
Do not suspend its scheduled backups or stop its operator. There is no Authentik VolSync job to trigger.

The final backup is a rollback safeguard. Apollo's import reads the stopped app's database directly
from the source primary; it does not restore that physical backup or copy the other shared databases.
If a source writer remains or the backup fails, hold the Apollo merge and fix the problem or restore
the old app through git.

### 2. Import and start Apollo

Merge the Apollo PR after the prior gate and credential setup. `authentik-database` waits for CNPG
Ready, and the app waits for that Kustomization. Capture import-job logs before job cleanup and confirm
`pg_dump`/`pg_restore` completed for `authentik`, rather than accepting an empty initialized database.
The destination owner is newly created `authentik`; source role passwords and ACLs are not copied.
Never start the old app while import or Apollo verification is underway.

```sh
kubectl --context apollo -n flux-system get kustomizations authentik-database authentik webfinger mealie
kubectl --context apollo -n security get externalsecrets,clusters.postgresql.cnpg.io,jobs,pvc
kubectl --context apollo -n security get helmreleases,deployments,httproutes
kubectl --context apollo -n security logs deployment/authentik-server
kubectl --context apollo -n security logs deployment/authentik-worker
kubectl --context apollo -n security get backups.postgresql.cnpg.io
```

Check server and worker startup for UID, filesystem, database TLS, and permission errors. UID 568 with
writable `/tmp` is supported by the inspected startup paths but has not been runtime-tested locally.
No writable media storage is configured because no files are being migrated. If the actual instance
needs local files, stop and resolve that storage requirement rather than adding ephemeral media.

WAL archiving and scheduled base backups use only Apollo's new bucket/path. They do not write into
the old cluster's archive. The scheduled backup's immediate first run must complete before cleanup.

### 3. Verify data, access, and backup

Compare the imported data to the source record. Pod readiness alone is insufficient. Check users,
groups, applications, provider settings, signing-key fingerprints, and representative flows. Complete
all of these before declaring the move successful:

- Both SSO HTTPRoutes and both WebFinger HTTPRoutes report current-generation Accepted and
  ResolvedRefs. LAN DNS points at `192.168.21.100`; public DNS belongs to Apollo's tunnel.
- LAN and off-LAN TLS and Authentik login succeed at the original hostname. Test login, logout,
  MFA, and a benign reversible configuration change; confirm both server and worker remain healthy.
- Fresh Mealie OIDC login preserves group mapping and verified-email behavior. Existing old-cluster
  consumers still reach the unchanged public hostname.
- WebFinger at `https://${SECRET_DOMAIN}/.well-known/webfinger?resource=acct:USER@${SECRET_DOMAIN}`
  returns the original issuer `https://sso.${SECRET_DOMAIN}/application/o/tailscale/` on both paths.
  Verify discovery and a fresh Tailscale login, not just an already-connected device.
- Send normal and forged X-Forwarded-For, Forwarded, X-Real-IP, X-Forwarded-Host, and
  X-Forwarded-Proto requests from LAN and off-LAN. Authentik must record the real client, keep the
  canonical HTTPS host, and reject spoofed identity headers. A Cloudflare edge rejection does not
  prove origin handling. Check both Authentik and Envoy logs without recording sensitive content.
- Verify SMTP delivery with an operator-selected test notification and confirm Prometheus scrapes
  server and worker. Confirm the NetworkPolicy permits the two Gateways and monitoring only.
- Verify an Apollo base backup completes and WAL archiving is healthy. Record the backup identifier
  and completion time. Keep the old data intact until Wave 2.

Routes are published by the Apollo PR after database readiness; verification therefore occurs during
the maintenance window. If data or identity checks fail, remove Apollo routes and stop Apollo writers
through git before restoring the old serving copy.

### 4. Cleanup and later upgrades

After data, login, and backup verification, remove the temporary source ExternalSecret and the
bootstrap/externalClusters patches from `database/kustomization.yaml`, retaining the PostgreSQL
parameter patch. The Postgres component then supplies normal recovery from the Apollo archive.
Keep the protected Cluster and database Kustomization. Remove the migration item from `hcc-apollo`;
do not rotate or revoke the source app password while it is still needed for rollback.

Keep the temporary database firewall path and `postgres-lb` for Paperless and TeslaMate. Keep the
old shared Dragonfly service for Paperless. Upgrade Authentik on Apollo only after cutover verification,
following each upstream release family in sequence with a fresh backup before schema changes. The
decision to retain 2025.10.3 is specific to this migration, not a long-term support policy.

## Rollback

Remove both Apollo apps' routes and stop Authentik server/worker and WebFinger through git. Verify
the workloads stopped. Apollo external-dns uses `upsert-only`, so route deletion alone does not release
its public records: have the operator remove or hand off only the two app records and their Apollo
ownership records after checking ownership. Ensure UniFi removes the corresponding Apollo LAN records.

Then revert the old disable commit through git. Confirm both HPAs, server/worker, WebFinger, public
Ingresses, and the old DNS ownership return. The source database has not undergone Authentik or
PostgreSQL upgrades. Writes accepted on Apollo after the import will not exist there; agree to that
loss before rollback. Do not restore the shared physical backup over Paperless or TeslaMate's newer
data. Retain a failed Apollo database for diagnosis until an explicit cleanup decision.

## Execution record

- Read-only checks: source Authentik server/worker 2025.10.3, PostgreSQL 16.2; database and public
  tables owned by `authentik`, only `plpgsql`, approximately 136 MB. Recent shared backups completed.
- All Apollo Flux Kustomizations were Ready before preparation; hcc5, hcc6, and hcc7 Longhorn nodes
  were Ready and Schedulable. Capacity and cross-VLAN database connectivity still require cutover checks.
- [ ] Both PRs reviewed and CI passed; operator supplied the required ESO items.
- [ ] Source writers stopped; public DNS released; final shared backup completed.
- [ ] Logical import completed and source/destination application data compared.
- [ ] LAN/public login, Mealie OIDC, WebFinger/Tailscale, SMTP, and proxy-header checks passed.
- [ ] First Apollo base backup and continuous WAL archiving verified.
- [ ] Temporary import configuration and credentials removed; plan archived under `plans/done/`.
