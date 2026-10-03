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

The operator confirmed Node-RED has no data or configured flows, so no Node-RED connection changes
are needed for this cutover. It remains scheduled for a fresh deployment after HA.

Preparation does not authorize merging the disable PR or changing live cluster state. Do not start the
maintenance window until all gates below pass.

## Prerequisites

- [x] Review and pass CI on both PRs before disabling HA.
- [x] Verify IPv4/mDNS and Lutron connectivity on hcc5, hcc6, and hcc7. All eight concurrent probe checks
  passed using distinct test addresses; the [completed record](20261003-iot-verification.md) preserves
  evidence. The HA-specific `192.168.6.100/22` binding remains a cutover check.
- [x] Remove the probes and apply `network.home.arpa/iot-ipv4: "true"` through approved Talos configuration.
  All three nodes are Ready and labeled; the full IoT/Thread label remains absent.
- [x] Verify Longhorn capacity for the 5Gi restored config PVC, temporary 5Gi restore volume, restic cache,
  and 5Gi database, each with its configured replica count on eligible disks.
- [x] Operator checks `RESTIC_REPOSITORY` in the old `home-assistant-config-volsync-r2` Secret and confirms
  the bucket/path is `tf-hcc-volsync/home-assistant-config` before merging either PR. The operator confirmed
  this exact bucket/path on 2026-10-03; agents did not read the Secret.
- [x] Identify references to the old IoT address `192.168.4.100/24` in HA's internal URL, firewall/DHCP
  configuration, and device callbacks. Prepare any required changes for `192.168.6.100/22`; prefer the
  canonical HA hostname for clients outside the IoT subnet.
- [x] Operator prepares the following `hcc-apollo` items and confirms ESO access. Do not paste values into
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
3. After both final backups succeed, with operator approval suspend the old app's Flux Kustomization,
   then pause its VolSync writer. This follows the Paperless cutover: suspension holds the already-disabled
   app configuration while the runtime writer pause is in place.

   ```sh
   flux suspend kustomization home-assistant --context main --namespace flux-system
   kubectl --context main -n default patch replicationsource home-assistant-config-r2 \
     --type merge -p '{"spec":{"paused":true}}'
   ```

   Verify the Kustomization is suspended, the ReplicationSource is paused, and no source mover/pruner
   remains active. Keep the old database/archive available for rollback; Apollo writes to a separate server
   and bucket. Leave this Kustomization suspended until rollback or old-cluster retirement.
4. With approval, merge the Apollo PR. VolSync preflight requires a real source snapshot; the config PVC
   references `home-assistant-config-bootstrap-migration-v1`. Database recovery reads
   `tf-hcc-cloudnativepg/home-assistant-pg-v1`, restores `home_assistant`, and writes only to
   `tf-hcc-apollo-cnpg/home-assistant-pg-apollo-v1`. The backup Kustomization remains suspended.
5. Check restored integrations, automations, local credentials, recorder history, Lutron control, LAN TLS,
   Tailscale login, and editor access. Verify the internal URL, address-specific firewall/DHCP settings,
   and device callbacks identified in preflight work with the new IoT address. Check logs for database,
   proxy-trust, and discovery errors without publishing credentials or device details. If a restored Matter integration remains configured, disable
   that integration in HA with operator approval; do not rewrite `.storage` files by hand.
6. After data verification, enable Apollo config backups through git and verify a nonempty restic snapshot.
   Verify a completed Apollo CNPG backup and WAL archiving. A forced move between nodes was originally
   planned; the operator declined that test after cutover (see scheduling decision below).

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

After the disable revert is merged and Apollo is stopped, resume the old `home-assistant` Flux
Kustomization with operator approval using
`flux resume kustomization home-assistant --context main --namespace flux-system`. Wait for the reverted
workload and routes to reconcile and verify HA. Then, with approval, resume its backup writer using
`kubectl --context main -n default patch replicationsource home-assistant-config-r2 --type merge -p '{"spec":{"paused":false}}'`.
Confirm the writer is unpaused and its scheduled backups resume; do not assume Flux clears the runtime pause.

## Validation

Both cluster kubeconform checks, Apollo policy lint, seven migration tests, and the full Apollo Flux render
passed during preparation. Rendered Services and routes were inspected for backend consistency.

## Evidence and remaining gates

- Matter API: zero paired nodes; entity-registry summary: no Matter integration entities.
- Multus and its config Ready; Multus DaemonSet ready on all three Apollo nodes; Cilium VLAN 2 bypass enabled.
- IPv4 probes passed on all three nodes, temporary resources were pruned, and approved Talos label applies
  completed without rebooting. hcc5, hcc6, and hcc7 are Ready with the IPv4 capability label.
- Longhorn capacity was rechecked on 2026-10-03: all disks Ready/Schedulable, 100% overprovisioning,
  zero reserved bytes, and roughly 75Gi of unscheduled capacity on each of hcc5 and hcc6. The restore's
  5Gi config claim, 5Gi temporary volume, 1Gi cache, and 5Gi database total 16Gi per node at three replicas;
  hcc7 has more headroom. Available physical space also clears the configured 25% minimum.
- The operator confirmed the source restic bucket/path, all four 1Password items with ESO access, and
  completion of the old-address review on 2026-10-03. Credential values were not read or recorded.
- Both refreshed PRs passed CI before #325 merged as `776757a54cb5769777b24376372003c55f5125d2` on
  2026-10-03. Flux applied that revision; HA/editor/Matter stopped, all three old Ingresses disappeared,
  and no HA Tailscale proxy resources remained. The recorder database stayed healthy.
- With operator approval, the final VolSync trigger `ha-cutover-v1` completed at `2026-10-03T15:09:06Z`
  with mover result `Successful`, snapshot `2c2c2042`, and 3,561 files totaling 50.355 MiB. The source
  reports `lastManualSync: ha-cutover-v1` and `Synchronizing: False`.
- CNPG Backup `home-assistant-migration-final` completed with ID `20261003T150812`, from
  `2026-10-03T15:08:12Z` to `2026-10-03T15:08:15Z`. Its begin/end WAL was
  `000000010000012C00000085`; `pg_stat_archiver` reported the matching backup-history file archived
  at `2026-10-03T15:08:17Z` with zero failures.
- After both backups succeeded, the approved old `home-assistant` Flux Kustomization suspension and
  `home-assistant-config-r2` ReplicationSource pause were applied. Read-only checks confirmed both flags
  `true`, no remaining HA source mover/pruner Jobs or Pods, and the old deployment still at zero replicas.
- PR #326 merged as `e1cb164c0e03c3ca14f52b2c44d6a65acbd36454` on 2026-10-03. Restore preflight
  confirmed an existing source snapshot, and VolSync restored final snapshot `2c2c2042` successfully at
  `2026-10-03T15:16:11Z`. The config PVC bound and Longhorn reported its clone completed and volume healthy.
- PostgreSQL recovery became healthy. The restored source history matched 8,705 states (maximum ID
  148650 and timestamp 1791039670.5619533) and 3,690 events (maximum ID 98187). New recorder writes
  subsequently appeared on Apollo. The transient recovery Job disappeared before its selected Barman
  backup ID could be captured; source aggregate comparison provides the recorded recovery evidence.
- HA and the editor became Ready on hcc6 with zero restarts. The actual pod passed IPv4 address/prefix,
  IoT/default route, source-bound Lutron TCP/mDNS, cluster DNS/API, and outbound DNS/TLS checks using
  `192.168.6.100/22`. LAN and Tailscale HA returned HTTPS 200 with valid TLS; the editor returned its
  expected redirect. All app/database/storage/Tailscale Flux Kustomizations reported Ready.
- The first Apollo CNPG backup completed as `20261003T151708`. Continuous archiving reported healthy;
  15 failures during recovery ended at `2026-10-03T15:16:20Z`, followed by successful archiving and the
  completed backup. The failure count remained unchanged on follow-up.
- The operator confirmed LAN/Tailscale login, existing integrations and automations, recorder history,
  Lutron device control, and editor access on 2026-10-03. Apollo config backups are enabled and verified below.
- PR #339 enabled Apollo config backups. The first sync completed at `2026-10-03T15:32:39Z` with mover
  result `Successful`: snapshot `2c55cfc2`, 3,567 files, and 50.362 MiB. The next scheduled sync is
  `2026-10-04T02:00:00Z`; no manual trigger was needed. The initial snapshot clone completed before
  attachment and the backup pod then ran successfully.
- PR #340 merged as `532826d465bade3e6f9a38098e72367319bb391d`. Read-only checks verified the restore
  preflight, ReplicationDestination, temporary restore PVC, and source ExternalSecrets/ObjectStore are gone.
  The database now references Apollo's own archive for recovery. All five remaining HA Kustomizations are
  Ready; HA serves HTTPS 200, PostgreSQL is healthy with successful archiving, and config backups retain
  their successful first snapshot and next scheduled run. The bound config PVC and rollback data remain intact.
- After pruning, the operator confirmed retirement of the migration-only `home-assistant-migration` and
  `home-assistant-pg-migration` 1Password items and exclusively scoped R2 keys on 2026-10-03. Application,
  Apollo backup, and old-cluster rollback credentials are retained. The old HA reconciliation suspension
  and writer pause remain in place for rollback.

## Scheduling decision

On 2026-10-03, the operator declined the proposed forced-node rescheduling test and selected normal
scheduling on any node with the required Multus setup. The existing IPv4 eligibility label covers hcc5,
hcc6, and hcc7. No hostname restriction or preference is needed because HA has no node-specific hardware.
The hcc5 test constraint was never deployed. Removing the original hcc6 preference changes the pod
template and causes a normal Recreate rollout; verify that rollout without forcing a particular node.

Migration restore, functional checks, Apollo backups, restore cleanup, and credential retirement are
complete. A cross-node HA functional test was not performed and is not a completion gate per the operator.
Matter/Thread remains deferred until the Apple TV is available. Keep old-cluster rollback resources until
Wave 2; confirm the previous instance is stopped before any replacement claims the shared IoT address.

## Reference patterns

[onedr0p](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/default/home-assistant/app/helmrelease.yaml)
and [szinn](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/apps/home/home-assistant/app/helmrelease.yaml)
provide rootless HA with Multus and persistent configuration.
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/default/home-assistant/home-assistant.yaml)
provides comparable memory sizing and writable cache separation.
[joryirving](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/home-automation/matter-server/helmrelease.yaml)
provides a future `net1` Matter/IPv6 route-information reference, not a requirement for this cutover.
No relevant HA/Matter implementation was found in Mafyuh/iac's current tree.
