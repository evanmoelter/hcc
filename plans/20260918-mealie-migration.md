# Mealie migration

## Scope and decisions

Mealie is the first household app prepared for Apollo. The operator selected it because it is
currently unused, allowing the PVC restore and recovery from the old in-tree Barman archive to be
proved before another app moves. Authentik remains on `main`; its version decision is deferred.
Upgrade Mealie and app-template on Apollo as part of the restore. Keep the existing PostgreSQL major,
OIDC provider, and `food.${SECRET_DOMAIN}` hostname. Add LAN access through the internal Gateway
and a standalone Tailscale HTTPS Ingress using the `mealie-apollo` tailnet hostname.

Mealie enforces its [verified-email requirement](https://github.com/mealie-recipes/mealie/releases/tag/v3.22.0).
The operator will configure and verify Authentik's claim mapping before cutover; its
[2025.10 default mapping](https://docs.goauthentik.io/releases/2025.10/#default-oauth-scope-mappings)
reports unverified email. Apollo cannot express a Flux dependency on Authentik in another cluster;
verify discovery and login again when Authentik migrates. AI credentials are omitted at the operator's request.

Use the [standard migration](./20260816-talos-migration.md) and the tested
[VolSync](../kubernetes/apollo/components/volsync/) and [Postgres](../docs/databases.md) lifecycles.
Do not merge both cutover PRs together. No live mutating commands are authorized by this document.

## Prepared changes

1. **Disable on main:** set the Mealie Deployment to zero replicas and remove its external Ingress.
   Retain its HelmRelease, PVC, database, Secrets, and backup configuration for final backups and rollback.
2. **Restore on Apollo:** restore the 5 GiB data PVC and the 5 GiB PostgreSQL database before starting
   the app. Include disabled LAN/public routes and Tailscale Ingress in the HelmRelease, and a
   suspended Apollo PVC backup lifecycle.

After inspecting restored data, activate routes and Tailscale Ingress through a follow-up git change.
After checking login and app behavior, activate PVC backups. This explicit gate implements the VolSync requirement to
verify data before publishing traffic or enabling backups. The CNPG component starts its independent
Apollo WAL archive and scheduled base backups after recovery.

## Before the maintenance window

Both PRs must pass review, schema validation, and rendering. Review the rendered old-cluster diff:
only Mealie's Deployment replica count and external Ingress should change.

The operator supplies these fields in `hcc-apollo`; agents do not read or write their values:

| Item | Fields and scope |
|---|---|
| `mealie` | Existing `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`; a new `RESTIC_PASSWORD` for Apollo backups |
| `mealie-volsync-migration` | Original `RESTIC_PASSWORD`; `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` with Object Read & Write on the old VolSync bucket for restic locks |
| `mealie-postgres-migration` | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` with Object Read on `tf-hcc-cloudnativepg` |
| `cloudflare-r2` | Existing shared `ACCOUNT_ID`; source and destination buckets are in this account |
| `volsync-r2`, `cnpg-r2` | Existing write credentials scoped to their respective Apollo buckets |

Confirm `tf-hcc-apollo-volsync/mealie` and `tf-hcc-apollo-cnpg/mealie/` are unused. A previous attempt
needs diagnosis and an explicit recovery decision; never silently reuse a partial destination archive.
The operator confirmed the old repository suffix is `tf-hcc-volsync/mealie-data`; it is explicit in
the preflight substitutions. Bucket names and paths stay in git; credentials and passwords stay in Secrets.

Check eligible Longhorn capacity for the database, permanent app PVC, retained temporary restore PVC,
and restic cache. Each main data volume uses three replicas; the three-node fleet needs capacity on
every node, not just enough space in aggregate. Confirm source app data before stopping it: record
representative recipes, user/group membership, and attachments if any. If unused means no recipes,
record that explicitly; preserved identities/configuration and file checks still matter.

Check that Apollo can resolve and reach the existing Authentik discovery URL. Preserve the existing
provider credentials and redirect URI; never enable password login as an implicit migration fallback.
For the additional tailnet URL, register `https://mealie-apollo.<tailnet-dns-name>/login` on the same
Authentik provider, retaining the existing public callback. Include `/login?direct=1` if the provider
uses RP-initiated logout, and add the tailnet origin if it enforces allowed origins; see
[Mealie's OIDC setup](https://docs.mealie.io/documentation/getting-started/authentication/oidc/).
Keep the canonical `BASE_URL` at the LAN/public hostname. Confirm the requested tailnet hostname is
available and the tailnet client can reach Authentik on `main`.

Confirm Authentik supplies `email_verified: true` for the intended Mealie users; leave Mealie's
verified-email enforcement enabled. Review any recipe-import, image-fetch, webhook, or action targets:
[newer Mealie blocks private HTTP destinations by default](https://github.com/mealie-recipes/mealie/releases/tag/v3.26.0).
If an existing integration needs a LAN destination, add only its required hostname or CIDR to
`HTTP_ALLOW_LIST` through Helm values before testing it.

## Merge gates

### 1. Stop the old app and establish final restore points

Merge only the disable PR. Wait for `main` Flux to apply its revision and for every Mealie pod to stop.
Confirm the external Ingress is gone and old external-dns releases `food.${SECRET_DOMAIN}` and its
ownership record. The database stays running and the PVC remains bound.

With separate approval for live mutations, trigger the final VolSync sync and an on-demand
`mealie-pg` CNPG Backup using the old `barmanObjectStore` method. Wait for both to complete after
the app stopped. Record the VolSync completion, CNPG Backup name/ID, and completion time here.
Suspend the old backup Flux Kustomization and pause its `ReplicationSource` after its final sync;
suspending Flux alone does not stop VolSync's schedule. Confirm no mover or pruner is still running.
Retain the paused state until Wave 2 or an explicit rollback.

Do not proceed using an earlier successful backup as evidence of this gate. If either final backup
fails, keep Apollo undeployed while diagnosing it, or roll back the disable PR.

### 2. Restore on Apollo

Merge the Apollo PR after the final backup gate and credential setup. Preflight requires an existing
restic snapshot; the app PVC explicitly references `mealie-bootstrap-migration-v1`. Storage readiness
requires a completed restore and bound PVC. The app also waits for `mealie-pg` recovery.

The database reads `tf-hcc-cloudnativepg/` with server name `mealie-pg-v1`, using source credentials
without a retention policy. It writes only to `tf-hcc-apollo-cnpg/mealie/` as `mealie-pg-apollo-v1`.
The new destination must pass the empty-archive safety check. Source ObjectStore endpoint configuration
is present for the recovery job as well as destination configuration for the normal Barman sidecar.

Inspect bootstrap logs before they disappear: confirm recovery from the old Barman archive, rather
than an empty `initdb`. Confirm the final backup was selected and replay completed. Inspect PVC
restore results and compare representative data with the source record. Preserve non-sensitive
verification evidence here; pod health alone does not prove recovery.
The upgraded app applies its database migrations to Apollo's restored copy. Verify migration completion
and app startup before publishing routes; the source database remains available for rollback.

Useful read-only checks:

```sh
kubectl --context apollo -n flux-system get kustomizations
kubectl --context apollo -n default get externalsecrets
kubectl --context apollo -n default get jobs,replicationdestinations,pvc
kubectl --context apollo -n default get cluster mealie-pg
kubectl --context apollo -n default logs job/mealie-restore-preflight-migration-v1
kubectl --context apollo -n default logs deployment/mealie
kubectl --context apollo -n default get backups.postgresql.cnpg.io
```

Routes and Tailscale Ingress remain unpublished during this gate. Use a read-only database/file
inspection or local port forward to inspect the restored application. End-to-end OIDC tests through
the registered public and tailnet hostnames follow access activation.

### 3. Activate and verify

Set `spec.values.route.internal.enabled`, `spec.values.route.external.enabled`, and
`spec.values.ingress.tailscale.enabled` to `true` in `app/helmrelease.yaml` through git.
Verify both HTTPRoutes report Accepted and ResolvedRefs as True for their current generation;
HelmRelease readiness alone does not establish route readiness.
Verify LAN DNS points to the internal Gateway, public DNS uses Apollo's tunnel alias, and TLS works
on both paths. Confirm public access from outside the LAN.

Get the assigned tailnet hostname with
`kubectl --context apollo -n default get ingress mealie-tailscale`. Verify a trusted HTTPS certificate
and Mealie response from a tailnet client, then test OIDC login and logout at that hostname. Check
that the Tailscale proxy uses the `tailscale-ingress` ProxyClass. HelmRelease readiness or an assigned
Ingress hostname alone does not prove tailnet connectivity or authentication.

Verify OIDC login through Authentik on `main`, admin/user group mapping, representative recipes and
attachments, and a new write. Check logs for database and permission errors. With an initially empty
app, create a disposable recipe and attachment to prove both stores can write after recovery.

The old app seeds `/app/data/.initialized`; the restore is expected to carry that file forward.
Apollo does not seed a new file during recovery. Before enabling PVC backups, confirm the restored
data directory contains that marker or another durable file. Preflight proves that a snapshot exists,
not that its contents are non-empty. If the directory is empty, investigate the restore before proceeding.

Remove the backup Kustomization's suspension in `ks-storage.yaml` through git. Wait for an actual
successful snapshot in Apollo's restic repository, and verify the first completed Apollo CNPG backup
and healthy WAL archiving. A successful mover with no restic snapshot does not satisfy the gate.

### 4. Remove one-time restore machinery

After data, login, writes, and both Apollo backups pass, make a cleanup commit:

- Remove the preflight Kustomization, storage's restore component, capacity replacement, preflight/VolSync
  dependencies, and ReplicationDestination health check. Keep PVC readiness, its protected manifest, its immutable
  `dataSourceRef`, and the same `mealie-storage` Kustomization.
- Remove the database's temporary source ObjectStore, source ExternalSecret, and externalClusters patch.
  Remove the patch deleting `cnpg.io/skipEmptyWalArchiveCheck` so future recovery can reuse Apollo's
  archive. Keep the PostgreSQL tuning patch and the same `mealie-database` Kustomization.
- Confirm temporary restore resources and temporary PVCs are removed, while app/database volumes remain
  healthy with three replicas. The operator revokes the old-bucket migration credentials afterward.

Keep all old app data and its paused VolSync writer through Wave 1. Move this complete plan and its
execution record to `plans/done/` only when the migration and cleanup gates have passed.

## Rollback

First set both HelmRelease routes and the Tailscale Ingress `enabled` values to `false` through git.
Confirm the tailnet Ingress/proxy is removed and DNS ownership is released. Cloudflare's `upsert-only`
policy will leave its CNAME/TXT records behind; the operator must remove the Apollo-owned records
before the old controller can reclaim the hostname. Stopping reconciliation alone does not
remove routes or stop workloads.

Stop the Apollo app through git and verify its pods are gone. Revert the old disable PR and verify
the old app and ingress return. Resume the old VolSync writer and its Flux Kustomization only with
operator approval. Apollo's backup paths are separate, but no restored writes flow back to the source:
rollback discards writes made after cutover. Retain Apollo storage for diagnosis; deleting its protected
database or PVC requires an explicit operator decision.

## Research and preparation evidence

The five requested community repository trees had no current Mealie deployment. The official image
is retained; no compatible Mealie image was found in `home-operations/containers`.
[Jory's Postgres component](https://github.com/joryirving/home-ops/blob/main/kubernetes/components/postgres/cluster.yaml)
informs recovery wiring, and [Mafyuh's VolSync PVC](https://github.com/Mafyuh/iac/blob/main/kubernetes/components/volsync/pvc.yaml)
uses an explicit restore destination reference. Apollo keeps its tested preflight and lifecycle separation.

Read-only checks on 2026-09-18 found all Apollo Flux Kustomizations Ready, the old Mealie Deployment
running v3.12.0, PostgreSQL 18.1, and 5 GiB database and app volumes. The old database's latest successful
backup was 2026-09-13, and the PVC's latest sync was 2026-09-18. These are preparation checks, not final
cutover backups or live recovery verification. Authentik upgrades remain a later decision.

## Execution record

- Apollo prerequisites: the operator confirmed the required credentials are ready and Authentik's
  verified-email configuration is complete on 2026-09-19.
- Old app disabled: verified on 2026-09-19 after main applied `2959631` (rollout fix PR #300).
  Mealie has zero replicas, no app pods, and no Ingress; public DNS and checked ownership records
  returned NXDOMAIN. The database remains healthy and the 5 GiB app PVC remains bound.
- Final source backups: verified after shutdown on 2026-09-19. VolSync completed manual trigger
  `mealie-final-20260919215607` at `21:57:03Z`. CNPG Backup `mealie-final-20260919215607` completed
  at `21:58:16Z` using `barmanObjectStore`, with backup ID `20260919T215811`.
  The old `mealie-backup` Flux Kustomization is suspended and `mealie-data-r2` is paused with no
  schedule. No Mealie backup jobs or mover pods remained at verification.
- Apollo restore: verified on 2026-09-19 after Apollo applied `ecd3ff7` (PR #298).
  Preflight, storage, database, and app Kustomizations became Ready. VolSync restored snapshot
  `b451cb5f`, taken at `21:56:54Z` during the final source sync, and completed at `22:18:10Z`.
  CNPG's `mealie-pg-1-full-recovery` job completed at `22:18:26Z`; its pod had already been
  deleted when inspected, so selection of source backup `20260919T215811` could not be verified
  directly. This evidence gap remains recorded; recovery is supported by the completed recovery
  job and source/Apollo aggregate comparisons, not pod readiness alone.
  Recipe, user, group, household, ingredient, instruction, and attachment record counts match the
  source. Restored recipe/user files and `.initialized` are present. Both permanent volumes are
  healthy with three replicas. Application database upgrades and startup completed successfully.
  The operator subsequently confirmed representative recipe/image checks passed.
- Access rollout: verified after Apollo applied `2eea07f` (PR #301). Both HTTPRoutes reported
  Accepted and ResolvedRefs for their current generation. LAN DNS points to the internal Gateway;
  LAN, Cloudflare public-path, and Tailscale HTTPS requests returned 200 with certificate verification.
  The Tailscale proxy uses the expected non-root security context and memory limit.
  The operator confirmed cellular access and the Tailscale recipe/image check. Fresh Tailscale
  login/logout confirmation is pending clarification after two OIDC state-mismatch callback errors.
- New writes: the operator created a temporary recipe, uploaded an image, and confirmed both persisted
  after refresh. Keep that test data through the first Apollo PVC backup.
- First Apollo database backup: `mealie-pg-20260919221734` completed using the Barman plugin,
  with backup ID `20260919T221904`. Continuous WAL archiving is healthy.
  The PVC backup lifecycle is enabled on its regular schedule. Verification of its first actual restic
  snapshot remains pending; restore machinery stays in place until that succeeds.
- Restore cleanup and credential revocation: pending.
