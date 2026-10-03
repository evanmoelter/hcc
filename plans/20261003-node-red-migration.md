# Node-RED migration

Preparation and execution record for the final household app in the
[Talos migration](20260816-talos-migration.md). Home Assistant migration is handled separately.

## Decisions and stack

The operator confirmed an empty rebuild, preserving LAN/Tailscale access and existing login behavior.
Read-only inspection found the main deployment healthy on 4.1.3. Its login-discovery endpoint reports
no editor authentication. The encrypted manifest has one credential field,
`NODE_RED_CREDENTIAL_SECRET`; only the field name was inspected. No secret values, flows, or PVC
settings were read. The old settings may use an automatically generated key rather than that environment
variable; the fresh Apollo configuration explicitly maps the supplied key.

Prepare two Graphite PRs, review both, and merge them separately:

1. Disable main: set the existing deployment to zero replicas and disable both Ingresses. Retain the
   release, PVC, secrets, and backup configuration through Wave 2.
2. Rebuild on Apollo: create a fresh PVC, app, internal HTTPRoute, Tailscale Ingress, and independent
   backup lifecycle. There is no restore, database, public route, or IoT attachment.

Hold both merges until Apollo Home Assistant is verified. Refresh the stack against main after that
work lands, preserving both sessions' namespace registrations and documentation changes. This is an
operator verification gate: the empty Node-RED runtime does not require Home Assistant to start, and
its editor should remain available for repair during an HA outage. The two apps therefore have no
hard Flux readiness dependency.

The fresh deployment uses upstream Node-RED 5.0.7 with Node.js 24 and the repository's app-template
5.2.1. The image and chart are pinned by digest. Node-RED 5 requires Node.js 22.9 or newer and recommends
24; no old flows, contributed modules, or project data are imported across the major-version change.
The full image retains native-module build tooling for palette installations. UID/GID 1000 is preserved
for Projects' Git/SSH identity, with matching VolSync mover identity. Other Apollo hardening remains in place.

No merge, final backup, suspension, restart, or other cluster mutation is authorized by this record.
Obtain approval for the concrete live actions at cutover.

## Operator preparation

Create item `node-red` in `hcc-apollo` with:

| Field | Purpose |
|---|---|
| `NODE_RED_CREDENTIAL_SECRET` | New application credential-encryption key for the empty deployment |
| `RESTIC_PASSWORD` | New password for Apollo's independent Node-RED restic repository |

Retain the old key and old backup credentials with the rollback copy. No secret values should be
shared in chat or committed. A Home Assistant token is not part of the old manifest's credential bundle;
configure a new token through Node-RED's credential UI when integrating the fresh instance.

Confirm `tf-hcc-apollo-volsync/node-red` is unused and existing Apollo R2 credentials are ready.
Check Longhorn has room on three eligible nodes for the 2 GiB claim plus backup snapshots and cache.
Confirm no new flows or credentials have been added to main since the decision to start fresh. If that
changes, stop and revise the migration method before disabling it.

## Cutover and verification

1. Confirm both PRs have passed CI/review and Apollo Home Assistant's operator verification is complete.
2. Merge only the disable PR. Wait for Flux, zero Node-RED pods, removal of both old Ingresses, and release
   of its tailnet name. Main's k8s-gateway must no longer advertise an app-specific record. Check the
   actual client resolver as well as UniFi; its wildcard fallback may remain during the outage, as
   documented in the [Paperless cutover](done/20260930-paperless-migration.md).
3. With explicit approval, trigger and verify a final old VolSync backup for rollback, then pause the
   old `node-red-data-r2` ReplicationSource. If the empty source produces no snapshot, record that result
   and obtain the operator's acceptance before proceeding. Apollo does not restore from this backup.
   Keep the old backup Kustomization and manifests; the approved pause must also prevent Flux from
   reinstating a scheduled writer. Main and Apollo use independent repositories.
4. Confirm the vault item, unused destination path, and storage capacity. Merge the Apollo PR and wait
   for `node-red-storage`, `node-red`, `node-red-tailscale`, and `node-red-backup` to become Ready.
5. Verify the new LAN record resolves to `192.168.21.100`, the HTTPRoute is Accepted with ResolvedRefs,
   and LAN and Tailscale HTTPS both work with trusted certificates. Check editor WebSocket connectivity
   and confirm the selected no-login behavior on both paths.
6. Check logs privately for filesystem, credential, module-loading, and startup errors. Deploy a harmless
   test flow. Verify palette installation, Projects initialization, and any intended Git/SSH workflow.
   After an operator-approved restart, confirm flows and saved credentials remain usable. Do not count
   HTTP readiness as application or integration verification.
7. Configure and verify the Home Assistant integration as described in [Node-RED operations](../docs/node-red.md).
   Confirm an event arrives and a harmless action works against Apollo Home Assistant.
8. Wait for the first scheduled Apollo backup or obtain approval for an on-demand sync. Confirm an actual
   restic snapshot exists, including initialized `/data` contents. A successful empty-directory sync
   does not establish a restore point. Record backup and application verification before closing migration.

Read-only status checks:

```sh
kubectl --context main -n flux-system get kustomizations node-red node-red-backup
kubectl --context main -n default get deployment node-red
kubectl --context main -n default get pods,ingresses
kubectl --context main -n default get replicationsource node-red-data-r2
kubectl --context apollo -n flux-system get kustomizations node-red-storage node-red node-red-tailscale node-red-backup
kubectl --context apollo -n default get helmrelease node-red
kubectl --context apollo -n default get pvc node-red-data
kubectl --context apollo -n default get pods,httproutes,ingresses
kubectl --context apollo -n default get replicationsource node-red-r2
```

## Rollback and completion

Disable Apollo's workload and both routes through git before reverting the old disable commit. Confirm
Apollo pods and its Tailscale proxy are stopped and DNS/tailnet names released. Preserve the Apollo PVC
and its backup repository; Apollo-only flows and credentials do not exist on the old copy. Resume the old
backup writer only after the old instance is serving again, with approval for any live mutation.

Keep the old app directory, PVC, secrets, and backups until Wave 2. There is no temporary restore machinery
to remove on Apollo. Once application checks and backups pass, update the parent migration's status and
archive this complete record under `plans/done/`, fixing its links. This PR does not claim cutover completion.

## Research

All five requested default-branch trees were inspected. Only
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/default/node-red/node-red.yaml)
contains a current Node-RED deployment. Its persistent `/data`, writable `/tmp`, HTTP probes, Projects,
UID 1000, and internal Gateway route are relevant. Apollo retains its own per-app OCI source and separate
storage/backup/Tailscale lifecycles. No current Node-RED path was found in onedr0p/home-ops,
szinn/k8s-homelab, Mafyuh/iac, or joryirving/home-ops, or an image in home-operations/containers.

Upstream references: [5.0 release requirements](https://github.com/node-red/node-red/releases/tag/5.0.0),
[chosen patch release](https://github.com/node-red/node-red/releases/tag/5.0.7),
[Docker image](https://github.com/node-red/node-red-docker/blob/main/README.md),
[entrypoint](https://github.com/node-red/node-red-docker/blob/main/.docker/scripts/entrypoint.sh),
[settings](https://github.com/node-red/node-red/blob/5.0.7/packages/node_modules/node-red/settings.js), and
[Projects Git/SSH implementation](https://github.com/node-red/node-red/blob/5.0.7/packages/node_modules/%40node-red/runtime/lib/storage/localfilesystem/projects/git/index.js).

## Execution record

- Operator approved the two-PR preparation, fresh state, and preserved access/login behavior.
- Isolated worktree created at `/private/tmp/hcc1-node-red`; Home Assistant work is separate.
- Source deployment readiness and disabled editor login were verified read-only. Only the encrypted
  credential field name was inspected. No credential values were read or copied.
- The upstream image digest and entrypoint were verified. No local Docker daemon is available, so image
  filesystem compatibility and palette/Projects behavior remain deployment checks.
- [ ] Operator confirms the Apollo vault item and unused backup path.
- Local validation passed: both cluster schema checks, 20 Conftest policy tests and 903 resource checks,
  all 135 Apollo render checks, settings syntax and required-key behavior, and targeted old-chart
  rendering with zero replicas and no Ingresses. Flate required an identical standalone validation copy
  because its linked-worktree source discovery fails; no manifest workaround was introduced.
- Independent review found no actionable defects. Runtime and cutover verification remain pending.
- [ ] Home Assistant verified; stack refreshed and both PRs pass CI/review.
- [ ] Main disabled, final rollback backup handled, old writer paused, and names released.
- [ ] Apollo deployed; access, flows, credentials, Projects, and Home Assistant integration verified.
- [ ] First actual Apollo snapshot verified; complete record archived.

### Review refresh, 2026-10-03

- Restacked both Node-RED branches onto main at `50ba4b3`, including the merged Home Assistant
  deployment and backup enablement. Preserved both applications' README entries and namespace
  registrations. The Home Assistant record contains operator verification of access, integrations,
  automations, recorder history, and Lutron control; its remaining backup/cleanup work stays separate.
- Removed duplicate Projects and default safe-mode environment variables, kept the UID exception in
  app documentation, and rewrapped the joined prose. The 512 MiB memory limit remains unchanged;
  palette installation and possible memory pressure remain deployment checks.
- Refreshed validation passed: both cluster schema checks, 20 policy tests and 957 resource checks,
  all 143 Apollo render checks in a standalone validation copy, and settings syntax verification.
