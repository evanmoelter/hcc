# Home Assistant migration

## Scope and decision

Prepare the standard two-PR stack: disable the old deployment and all three Ingresses, then restore HA
on Apollo. Keep HA 2025.12.5 and code-server 4.107.0 during cutover; use Apollo's app-template chart.
Retain LAN HA/editor and Tailscale HA access. Do not add OIDC or a public route during migration.

The operator does not yet own the Apple TV and selected migration without Matter/Thread. A read-only
`get_nodes` WebSocket query to the existing Matter Server returned `paired_node_count: 0`; the HA entity
registry contained no Matter entities. This establishes no currently paired Matter devices, not an empty
Matter filesystem. Retain its old PVC and omit Matter from Apollo. Existing Lutron Caséta entities require
preserving HA's IPv4 IoT access. Apple TV, IPv6/Thread tests, Matter runtime selection, and Matter backups
are deferred; IPv4/mDNS verification remains a cutover prerequisite.

The isolated worktree is `/private/tmp/hcc1-home-assistant`. Preparation does not authorize merging the
disable PR or changing live cluster state. Do not start the maintenance window until all gates below pass.

## Prerequisites

- [ ] Review and pass CI on both PRs before disabling HA.
- [ ] Verify IPv4 on `net1`, the `192.168.6.100/22` address, an unchanged Cilium default route, gateway
  reachability, mDNS, and connectivity to the existing Lutron bridge on hcc6 and one alternative node.
  Follow the git-managed test workload procedure in [networking](../docs/networking.md#deployment-verification);
  obtain approval before deploying tests. Do not print bridge credentials or device inventories.
- [ ] Stop/remove the test workload before HA claims its address. Through approved Talos configuration,
  label only passing nodes `network.home.arpa/iot-ipv4: "true"`. Leave the full IoT/Thread label absent.
- [ ] Verify Longhorn capacity for the 5Gi restored config PVC, temporary 5Gi restore volume, restic cache,
  and 5Gi database, each with its configured replica count on eligible disks.
- [ ] Operator confirms the old restic repository is `tf-hcc-volsync/home-assistant-config`. The bucket is
  documented; the path is provisional because agents do not read backup Secrets.
- [ ] Operator prepares the following `hcc-apollo` items and confirms ESO access. Do not paste values into
  chat, commits, or PRs. Shared `cloudflare-r2`, `volsync-r2`, and `cnpg-r2` items already serve Apollo.

| Item | Fields and scope |
|---|---|
| `home-assistant-app` | Copy the existing HA application's credential environment fields with their exact uppercase names. Keep only required application credentials; exclude recorder URL, proxy CIDRs, timezone, and backup credentials. |
| `home-assistant-migration` | Original `RESTIC_PASSWORD`; `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` scoped read/write to the old VolSync bucket (restore locks require writes). |
| `home-assistant-pg-migration` | `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` scoped read-only to the old CNPG bucket. |
| `home-assistant-config` | A new `RESTIC_PASSWORD` for Apollo's config backup repository. |

## Cutover

1. With operator approval, merge only the disable PR. Wait for the old HA deployment to reach zero,
   including its editor and Matter containers, and for both LAN Ingresses and Tailscale identity to be
   released. Keep PVCs, database, Secrets, and backup resources intact.
2. Request approval for these final-backup commands before running them. The VolSync command captures
   the stopped config volume; CNPG captures the recorder database. Record completion and the final
   backup ID/time before continuing:

   ```sh
   kubectl --context main -n default patch replicationsource home-assistant-config-r2 \
     --type merge -p '{"spec":{"trigger":{"manual":"ha-cutover-v1"}}}'
   kubectl --context main -n default create -f - <<'YAML'
   apiVersion: postgresql.cnpg.io/v1
   kind: Backup
   metadata:
     name: home-assistant-migration-final
   spec:
     cluster:
       name: home-assistant-pg
     method: barmanObjectStore
   YAML
   ```

   Require `status.lastManualSync == ha-cutover-v1` and a successful sync, and CNPG Backup phase
   `completed`. Confirm archived WAL is current; never rely solely on a scheduled-backup timestamp.
3. With approval, suspend the old VolSync writer using
   `kubectl --context main -n default patch replicationsource home-assistant-config-r2 --type merge -p '{"spec":{"paused":true}}'`.
   Commit the same paused field through git so Flux preserves it. Verify there is no active mover or prune
   job. Keep the old database/archive available for rollback; Apollo writes to a separate server and bucket.
4. With approval, merge the Apollo PR. VolSync preflight requires a real source snapshot; the config PVC
   references `home-assistant-config-bootstrap-migration-v1`. Database recovery reads
   `tf-hcc-cloudnativepg/home-assistant-pg-v1`, restores `home_assistant`, and writes only to
   `tf-hcc-apollo-cnpg/home-assistant-pg-apollo-v1`. The backup Kustomization remains suspended.
5. Check restored integrations, automations, local credentials, recorder history, Lutron control, LAN TLS,
   Tailscale login, and editor access. Check logs for database, proxy-trust, and discovery errors without
   publishing credentials or device details. If a restored Matter integration remains configured, disable
   that integration in HA with operator approval; do not rewrite `.storage` files by hand.
6. After data verification, enable Apollo config backups through git and verify a nonempty restic snapshot.
   Verify a completed Apollo CNPG backup and WAL archiving. Schedule an approved move from hcc6 to a
   verified alternative and confirm IPv4 address, config, and device control survive.

## Cleanup and rollback

After successful verification and first Apollo backups, remove restore preflight and temporary source
credentials/ObjectStore, the storage restore component/replacement and temporary health check/dependencies,
and the database source patch. Preserve the bound PVC's immutable dataSourceRef, app/database settings,
and permanent lifecycle Kustomizations. Resume normal Apollo config backups and retire the old migration
credentials through the operator. Record evidence here before archiving this full plan in `plans/done/`.

For rollback, stop Apollo and release its LAN/Tailscale identities and static IoT address before reverting
old-cluster disable. Pause Apollo backup writing. The old app/PVC/database/Matter PVC remain intact; returning
to them loses writes made on Apollo, which requires an explicit operator decision. Do not delete the new
PVC or recovered database until the failure has been investigated and the operator approves cleanup.

## Validation

Both cluster kubeconform checks, Apollo policy lint, seven migration tests, and the full Apollo Flux render
passed during preparation. Flate was run in a clean temporary checkout because source resolution in the
linked worktree used the wrong tree. Rendered Services and routes were inspected for backend consistency.

## Evidence and remaining gates

- Matter API: zero paired nodes; entity-registry summary: no Matter integration entities.
- Multus and its config Ready; Multus DaemonSet ready on all three Apollo nodes; Cilium VLAN 2 bypass enabled.
- No Apollo IoT capability labels were present. IPv4/mDNS verification, operator credentials, final backups,
  cutover, functional checks, rescheduling, and cleanup remain pending.

## Reference patterns

[onedr0p](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/default/home-assistant/app/helmrelease.yaml)
and [szinn](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/apps/home/home-assistant/app/helmrelease.yaml)
provide rootless HA with Multus and persistent configuration.
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/default/home-assistant/home-assistant.yaml)
provides comparable memory sizing and writable cache separation.
[joryirving](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/home-automation/matter-server/helmrelease.yaml)
provides a future `net1` Matter/IPv6 route-information reference, not a requirement for this cutover.
No relevant HA/Matter implementation was found in Mafyuh/iac's current tree.
