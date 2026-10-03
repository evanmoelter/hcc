# Main single-node recovery

## Decision and scope

Retain hcc3 as a powered-off, single-node k3s recovery environment for approximately one week after the
Apollo cutovers. Start only the applications or databases needed to retrieve data. The retained data is
from the old cluster's cutovers; it does not include subsequent Apollo writes.

The operator selected this approach on 2026-10-03. hcc4 is already evacuated, removed, and powered off;
the tablet is absent from Kubernetes, etcd, and Longhorn. The remaining live members are hcc, hcc2, and
hcc3. The [Talos migration record](20260816-talos-migration.md#execution-waves) preserves those removals.
The downsizing below has not run. Live changes and the eventual disk wipes require approval under
[AGENTS.md](../AGENTS.md#ground-rules).

## Capacity and preparation

The 2026-10-03 inspection found four CPU cores, 16 GiB RAM, and a 360 GiB Longhorn filesystem on hcc3.
CPU use was about 20%; Linux reported about 10.5 GiB available memory, including reclaimable cache.
All fourteen retained volumes total about 166 GiB provisioned and 11 GiB actual data. hcc3 already has
healthy copies of all ten application/database volumes. The four VolSync cache volumes have their only
copies on hcc2 and must move before it is removed. Recheck these observations at execution time.

This PR prepares the configuration while the three-node cluster is still running:

| Resource | Preparation |
|---|---|
| Longhorn | One replica by default for newly provisioned volumes; one instance of each CSI controller and the UI. Existing volumes retain their current replica counts until explicitly changed. |
| Longhorn node scheduling | `allowScheduling: false` on hcc and hcc2 through the separate `longhorn-recovery-nodes` Flux Kustomization. Existing disks and replicas are preserved; eviction is not requested by git. |
| Dragonfly and cloudflared | One replica each. |
| System upgrade controller | Zero replicas; retain the controller configuration and k3s Plans. |
| VolSync | Commit the four existing `paused: true` settings. |
| CNPG scheduled backups | Suspend all three schedules. Running databases can still archive WAL through their existing configuration. |

Existing single-instance CNPG clusters and disabled migrated workloads remain in place. Keep the
Longhorn managers, engine images, and instance managers available on all three nodes during evacuation;
restricting those components to hcc3 first would strand replicas on the Odroids.

The Odroids already have Kubernetes's `dedicated=storage:NoSchedule` taint, which Longhorn tolerates.
Longhorn's own node scheduling flag prevents new or rebuilt replicas from landing there. Kubernetes
taints alone do not enforce this storage placement. The minimal Node manifests own only their names and
scheduling flags; they omit disks and eviction state. Pruning is disabled for these resources.

The chart supplies the default StorageClass through a ConfigMap, and Longhorn's
[controller recreates that StorageClass when its configuration changes](https://github.com/longhorn/longhorn-manager/blob/v1.6.4/controller/kubernetes_configmap_controller.go).
Let it reconcile the new default; do not hand-apply a replacement StorageClass. Bound PVCs retain their
volumes. Changing defaults does not reduce existing volume replica counts.

## Order of operations

### 1. Merge preparation and establish the recovery boundary

Merge this PR and wait for the affected Flux Kustomizations and HelmReleases to reconcile. Verify the
Longhorn StorageClass and default-replica-count setting are both one, its CSI deployments and UI each
have one ready replica, Dragonfly/cloudflared each have one ready replica, and the system upgrade
controller has zero replicas with no upgrade Jobs running.
Verify `longhorn-recovery-nodes` is Ready and both Odroids have Longhorn scheduling disabled while
hcc3 remains Ready/Schedulable. Existing replicas on the Odroids remain usable at this stage.

Confirm the Apollo migration and backup verification gates, including Node-RED, have passed. Keep all
migrated main workloads at zero replicas and their routes disabled. All four main ReplicationSources
must be paused, with no mover or prune Jobs running, and all three ScheduledBackups must be suspended.
Preserve existing suspended app Kustomizations. Their files will not reconcile until resumed: if a live
ScheduledBackup beneath one is still active, explicitly suspend that object during the approved
maintenance instead of broadly resuming the app Kustomization.

Confirm household clients and infrastructure no longer depend on the old Pi-hole, DNS, or other main
services before the eventual shutdown. Retain the old network addresses and recovery credentials until
the retention window ends. Verify access directly to hcc3's API at `192.168.4.13:6443` and through the
main VIP at `192.168.6.5:6443`; use `--context main` for all Kubernetes commands.

Take a named `k3s etcd-snapshot save` on hcc3. The operator preserves an off-node copy and the matching
server token using the existing secure storage process; do not print or commit either. An etcd snapshot
does not back up Longhorn data. Keep the verified application backups as the independent data copy.

### 2. Consolidate Longhorn onto hcc3

Record the live PVC-to-volume mapping, replica locations, and health before changing anything. Include
detached volumes, cache PVCs, and any temporary VolSync volumes; stop if an unexpected active writer or
unhealthy volume appears. Confirm hcc3's disk is Ready/Schedulable with enough reserved and actual space.

Cordon hcc and hcc2. With their Longhorn scheduling already disabled by git, request replica eviction:

```sh
kubectl --context main cordon hcc hcc2
kubectl --context main -n storage patch nodes.longhorn.io hcc --type=merge \
  -p '{"spec":{"evictionRequested":true}}'
kubectl --context main -n storage patch nodes.longhorn.io hcc2 --type=merge \
  -p '{"spec":{"evictionRequested":true}}'
```

With both source nodes marked for eviction, reduce `spec.numberOfReplicas` to one on each audited
Longhorn Volume. These are controller-created runtime objects, not manifests reconciled from git.
Apply the change to the reviewed volume names, not an uninspected cluster-wide list:

```sh
kubectl --context main -n storage patch volumes.longhorn.io <reviewed-volume-name> --type=merge \
  -p '{"spec":{"numberOfReplicas":1}}'
```

Do not wait for eviction to finish while volumes still demand three copies on one eligible node.
Longhorn attaches idle volumes as needed and creates a replacement for a sole cache replica before
evicting it. Its [eviction cleanup retains the last healthy copy](https://github.com/longhorn/longhorn-manager/blob/v1.6.4/controller/volume_controller.go).
Never delete a replica, PVC, or volume to force progress.

**Gate:** Every retained volume has its requested single healthy replica on hcc3, with no failed or
rebuilding replicas. Both Odroids report zero scheduled replicas/backing images and have no remaining
replica CRs. Volumes attached for evacuation return to their previous detached state; active volumes
remain healthy. Compare against the saved PVC inventory, including all four cache volumes.

### 3. Drain the Odroids while preserving etcd quorum

Drain hcc and then hcc2 with `--ignore-daemonsets --delete-emptydir-data`, respecting disruption budgets
and waiting for replacement pods to become ready between drains. Do not use force or bypass eviction.
The Pi-hole RWX share manager may need to move from an Odroid to hcc3; verify it and its volume afterward.
Draining pods does not stop the host's k3s/etcd service. Leave both services running for the next step.

Remove the abandoned `cilium-test` namespace during this approved maintenance after confirming it still
contains only connectivity-test fixtures and no PVCs. Its cross-node affinity and host-port requirements
cannot be satisfied by one general-purpose node. This namespace is not managed by the repository.

**Gate:** All remaining application and platform pods are ready on hcc3, apart from the node-local
DaemonSets still on the Odroids. hcc3 has no memory/disk pressure, its required services have endpoints,
and all three etcd members are healthy. Resolve any disruption-budget or scheduling blocker before
changing membership.

After these gates pass, suspend `longhorn-recovery-nodes` before deleting either Kubernetes node:

```sh
flux --context main suspend kustomization longhorn-recovery-nodes -n flux-system
```

The applied scheduling flags remain false. Suspending this dedicated Kustomization prevents Flux from
recreating the empty Longhorn Node records after Longhorn deletes them during node retirement.

### 4. Contract etcd from three members to two

Request removal of hcc while all three k3s services are still running:

```sh
kubectl --context main annotate node hcc etcd.k3s.cattle.io/remove=true
```

K3s's [managed member controller](https://github.com/k3s-io/k3s/blob/v1.32.4%2Bk3s1/pkg/etcd/member_controller.go)
removes the member and records `etcd.k3s.cattle.io/removed-node-name`. Wait for that annotation and verify
the actual etcd member list contains only hcc2 and hcc3, both healthy. Kubernetes node count alone is
not a membership check; use authenticated etcd MemberList/Status or equivalent etcdctl queries.

Then disable and stop k3s on hcc, power it off, and delete its Kubernetes node record. Verify Longhorn
removes its empty node record and the API VIP still responds. Keep hcc2 and hcc3 running throughout.

### 5. Contract etcd from two members to one

**Do not stop hcc2 first. Both members are required to commit its removal.**
[Etcd membership changes require the current quorum](https://etcd.io/docs/v3.5/op-guide/runtime-configuration/).
Unlike the previous hcc4 removal, stopping the target before deleting its node would lose quorum here.

While hcc2 and hcc3 are both healthy, request removal:

```sh
kubectl --context main annotate node hcc2 etcd.k3s.cattle.io/remove=true
```

Wait for the removed-node-name annotation and verify exactly one voting member, hcc3, with a healthy
endpoint. Then promptly disable and stop k3s on hcc2, power it off, and delete its Kubernetes node record.
Do not run cluster-reset as part of this planned transition. If membership verification fails, stop and
diagnose with the still-required members running.

Remove hcc and hcc2 from Ansible inventory, unregister `longhorn/ks-recovery.yaml` from the storage
namespace, and remove that Kustomization and its node manifests in a follow-up commit after retirement.
Pruning is disabled, so this cleanup does not delete storage. Both nodes remain inventoried in this
preparation PR because they are still live.

### 6. Prove independent recovery, then retain hcc3

With both Odroids powered off, verify hcc3 is the only Kubernetes, etcd, and Longhorn node. Check the
API VIP, CoreDNS, Cilium, Longhorn attachment, and all three existing CNPG clusters. Validate local data
recovery with an approved read-only file check and database query; do not print sensitive contents.
Temporarily attach and verify previously detached application volumes without starting duplicate app
writers. Detach them afterward.

Take a new named etcd snapshot after membership contraction. Perform an approved graceful reboot of
hcc3 and repeat the checks with both Odroids still off. Keep migrated app replicas at zero, routes
disabled, and backup jobs paused throughout. This proves the recovery environment can cold-start
without another etcd member or an Odroid storage replica.

After the checks pass and old DNS dependencies are cleared, power off hcc3 for the agreed retention
window. Record completion, snapshots, volume coverage, restart verification, and the agreed expiry here.
Leave hcc3's k3s service enabled so it starts on power-up. No disk wipe is part of this procedure.

## Recovery and release

Boot hcc3 alone, verify the API and Longhorn, and retrieve only the required data. Before enabling any
old app, ensure it cannot conflict with Apollo's app writers, IoT addresses, DNS, tailnet identity, or
backup repositories. Prepare any required GitOps changes explicitly; reverting an entire migration
commit can re-enable routes and backups together. hcc3 has no node or local-storage redundancy.

Keep the Odroid disks untouched until the independent restart check passes. hcc4 can be reprovisioned
separately. Wiping/transplanting the Odroid SSDs and eventually wiping hcc3 still require explicit
operator approval. Retain main's manifests, encrypted secrets, recovery credentials, and required
network paths until the operator ends the recovery window.

## Execution record

- [ ] Preparation PR merged and reconciled; migrations/backups verified.
- [ ] All retained volume replicas consolidated onto hcc3.
- [ ] Odroids drained; obsolete connectivity tests removed.
- [ ] hcc removed from etcd, Kubernetes, Longhorn, and inventory.
- [ ] hcc2 removed from etcd, Kubernetes, Longhorn, and inventory.
- [ ] Single-node data access and cold restart verified; final etcd snapshot preserved.
- [ ] hcc3 powered off; retention expiry agreed.
- [ ] Operator releases retained hardware and credentials for final cleanup.
