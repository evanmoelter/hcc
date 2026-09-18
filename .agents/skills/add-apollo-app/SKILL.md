---
name: add-apollo-app
description: Add a new application to the Apollo Kubernetes cluster, from app research and operator decisions through Flux manifests and validation. Use for new-app onboarding; existing apps moving from kubernetes/main follow the migration plan instead.
---

# Add an Apollo app

Implement a new app under `kubernetes/apollo/apps/<namespace>/<app>/`. Read
[AGENTS.md](../../../AGENTS.md) first; it owns repository policy. Run repository commands from the
checkout root and resolve this skill's links relative to their containing file.

## Establish scope and research

Check both cluster trees for the app and read the relevant parts of
[the migration plan](../../../plans/20260816-talos-migration.md). If it already runs on `main`, explain
that this is a migration and use that plan instead of treating its data or hostname as new.
Do not generate an old-cluster disable change as part of this skill.

Inspect one or two current Apollo apps with similar needs. Useful starting points:

- [Gatus](../../../kubernetes/apollo/apps/monitoring/gatus/) for app-template, app-owned OCI source,
  probes, metrics, configuration, and ESO credentials.
- [Echo](../../../kubernetes/apollo/apps/network/echo-server/) for a dedicated chart and dual Gateway routes.
- [Kube-ops-view](../../../kubernetes/apollo/apps/monitoring/kube-ops-view/) for separate Tailscale ingress.

Use [community discovery](references/community.md) to find app-specific examples, then verify their
ports, probes, mounts, configuration, image identity, and dependencies against upstream documentation
and the selected chart. Check current releases and compatibility; do not inherit a reference repo's pins.
Prefer a usable app-specific chart, otherwise bjw-s app-template. For the latter, check compatible
`home-operations/containers` images before upstream images or custom builds.

Report the proposed deployment and sources before implementation. Ask only about decisions that
research and existing user instructions cannot settle: intended LAN/public/Tailscale access and
authentication, data durability and backup needs, unusual capacity or hardware requirements, or
material chart/image tradeoffs. A community app's public route is not permission to expose this app.
Propose the app name, an existing namespace, and ordinary technical settings rather than making the
operator choose documented ports or repeat settled conventions. If a new namespace is needed, explain why.

For missing credentials, propose 1Password item names and exact field labels for the operator to create
in `hcc-apollo`; get confirmation of existing names rather than inventing them. Never request secret
values. Wait for explicit answers to blocking decisions; continue independent research while waiting.

## Select the required integrations

Read only the docs needed by this app. These are the maintained integration instructions:

| App needs | Read and apply |
|---|---|
| Secrets or configuration reloads | [Secrets](../../../docs/secrets.md): ESO's `onepassword` store, dependency on `onepassword-store`, workload-level Reloader opt-in when needed. |
| Persistent files | [Storage](../../../docs/storage.md) and [VolSync lifecycle usage](../../../kubernetes/apollo/components/volsync/README.md): app-owned PVC in permanent storage, separate backups, `longhorn-config` dependency and replica capacity. |
| PostgreSQL | [Databases](../../../docs/databases.md): separate database Kustomization and readiness gate, `postgres` plus explicit `postgres/init` for a new database. |
| Redis-compatible service | [Dragonfly integration](../../../docs/databases.md#dragonfly): per-app instance, credentials, readiness, and memory headroom; confirm whether its data is disposable. |
| HTTP exposure | [Gateway](../../../docs/gateway.md) and [DNS](../../../docs/dns.md): internal-only route for LAN, separate internal/external routes for dual access, and app-specific proxy trust. |
| Tailnet access | [Tailscale](../../../docs/tailscale.md): separate Ingress and lifecycle depending on `tailscale-config` and the app. |
| Raw LoadBalancer or IoT networking | [Networking](../../../docs/networking.md): address allocation, Multus attachment, and verified node eligibility. |
| Metrics or availability checks | [Monitoring](../../../docs/monitoring.md): existing scrape and public-path check patterns; choose checks appropriate to the app. |

For a **new PVC**, omit restore preflight, the restore component, restore IDs, and `dataSourceRef`.
Use the backup lifecycle for durable files selected for backup. Set a distinct `APP` for each backup
stream and `CLAIM` when it differs; protect durable PVCs from pruning. An empty directory does not
produce a restic snapshot, so account for first-run data before claiming backup success.

For a **new PostgreSQL database**, the base component's default is recovery, not initialization.
Add `postgres/init` after the base, supply a tag-and-digest-pinned PostgreSQL image compatible with
the app, and use the image's actual PostgreSQL UID/GID. Start from the linked database fixture for dependencies and
health expressions, then add current required policies and validate it. After verifying app data and
the first Apollo backup, remove the init opt-in in a cleanup change while preserving the Cluster and
owning Kustomization. Include this follow-up in the handoff if deployment has not happened yet.

Check actual available storage, including replica placement, when sizing durable volumes; hcc7's disks
do not combine into one replica's capacity. If live checks are unavailable, record capacity as unverified.
Missing platform readiness or credentials can leave deployment blocked without preventing manifest work.
Do not substitute another storage, database, or secret mechanism to bypass a missing prerequisite.

## Build and register the app

Start with `ks.yaml` and `app/{kustomization,ocirepository,helmrelease}.yaml`. Add only the integrations
the app needs, with a separate Flux Kustomization for each lifecycle. For a new PVC-backed app, use
`ks-storage.yaml` for storage and backup documents and `storage/` for the app-owned PVCs. Order them
storage → app → backup. Put a database behind `ks-cluster.yaml`; the app depends on database readiness.
Components compose into `spec.path` and cannot configure their owning Flux Kustomization.

Apply AGENTS.md conventions and the [lint policies](../../../docs/linting.md), including:

- App-owned OCIRepository with both `ref.tag` and `ref.digest`, preserving signature verification when
  configured; pinned image tag and digest; schema comments matching the chosen chart/API.
- Explicit local Flux deletion policy, readiness, retry/timeout settings, and Helm failure handling.
  Inspect current Apollo examples; do not assume root patches supply defaults.
- Concrete `dependsOn` names from the current tree: configured storage, database, secret store,
  ingress, and identity as used. Put readiness checks on the lifecycle that owns each resource.
- UID/GID 568 and the repository's hardened contexts where the image supports them; explain narrow
  exceptions. Set CPU and memory requests and a memory limit, with CPU limits only when justified.
- App-specific health probes, writable temporary mounts for a read-only root, and an update strategy
  compatible with the app's state and volume access mode.
- Configuration in Helm values where supported; secret references via ESO; `${SECRET_DOMAIN}` and
  `${TIMEZONE}` substitutions. Do not copy credentials, domains, addresses, or identities from examples.

Register `ks.yaml` and every satellite in the namespace's `kustomization.yaml`, and every resource in
its local `kustomization.yaml`. For a new namespace, follow existing namespace policy and verify its
inclusion in the Flux root build. Check reachability from `kubernetes/apollo/flux`, not just file existence.

## Validate and hand off

Run from the repository root using the Mise-managed tools:

```sh
task kubernetes:kubeconform CLUSTER=apollo
task kubernetes:lint CLUSTER=apollo
flate test all --path ./kubernetes/apollo/flux
```

Inspect the affected rendered manifests for the expected workload, routes, secret references, PVCs,
database, and backup resources. Check substitutions and chart-generated Service names and ports.
Schema validation alone cannot verify chart values or registration. Do not retrieve secret values to
make rendering work; report unavailable substitutions and any validation limitations.

Update README/AGENTS or relevant docs only for new architecture or reusable operational facts, avoiding
copies of manifest configuration. Follow the available Graphite workflow when committing or opening
PRs is in scope. Onboarding is not authorization to merge, cut over traffic, or mutate the live cluster.

Finish with what was added, validation results, operator credential/prerequisite work, and the concrete
post-deployment checks: Flux/Helm readiness, real application behavior, each intended access path,
authentication/proxy trust where relevant, and the first successful offsite backup for durable data.
Distinguish rendered configuration from observed live behavior. Read-only checks use explicit
`--context apollo`; any live mutation still needs the operator's explicit approval under AGENTS.md.
