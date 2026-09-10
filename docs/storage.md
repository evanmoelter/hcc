# Apollo storage

Longhorn 1.12.1 runs in `storage`, using the V1 data engine and the Talos user volumes. The namespace permits
privileged pods because Longhorn's manager and CSI components need host access. The chart's security contexts
are retained for these system components. Talos already declares the `iscsi-tools` and `util-linux-tools`
extensions and the required `rshared` kubelet mounts.

## Disks and replicas

| Node | Longhorn disks | Registration |
|---|---|---|
| hcc5, hcc6 | NVMe at `/var/mnt/longhorn` | active configuration |
| hcc7 | NVMe at `/var/mnt/longhorn`, SATA SSD at `/var/mnt/longhorn-sata` | active configuration |
| hcc8 | NVMe at `/var/mnt/longhorn` | prepared; awaiting a switch port and cluster join |

The HDDs on hcc5 and hcc6 are excluded. Disks have no tags and share one pool. Talos reserves EPHEMERAL
separately, so Longhorn reserves no additional bytes on these dedicated user volumes. Scheduling keeps 25%
free and limits reservation to 100% of capacity.

The default `longhorn` StorageClass uses three replicas on distinct nodes, with best-effort data locality
and replica balancing. `longhorn-two-replicas` is an explicit per-app choice when offsite restore is acceptable.
Both use ext4 inside volumes and delete the volume when its PVC is deleted. The host user volumes use XFS.

Apollo starts with hcc5 through hcc7. App migrations may proceed before hcc8 joins. During a node outage,
three-replica volumes have two available replicas; restore the node and wait for healthy replicas before
maintaining another node. Confirm schedulable capacity before each app migration.

## Flux ownership

`longhorn` reconciles the chart and ServiceMonitor. `longhorn-config` depends on it, owns the disk assignments
and additional StorageClass, and waits for every registered disk to be Ready and Schedulable.
Storage consumers should depend on `longhorn-config` so they wait for usable disks.

Automatic default disk creation is restricted to labeled Kubernetes nodes; Apollo gives no nodes that label.
The Longhorn Node resources declare each allowed path explicitly. Flux pruning is disabled on these resources
so removing a file does not delete storage configuration. Perform scheduling and disk changes through git;
UI edits to managed fields are reverted. Disk removal requires disabling scheduling and evacuating replicas first.

To add hcc8, first join it with the existing Talos configuration and verify its user volume and kubelet mount.
Then add `./hcc8.yaml` to `kubernetes/apollo/apps/storage/longhorn/config/kustomization.yaml` and validate the tree.
The prepared file is deliberately unregistered: Longhorn removes Node resources whose Kubernetes node is absent.
Do not retire an old-cluster node just to free this port before the migration plan permits retirement.

## Verification and follow-up

After Flux deploys the change, inspect status without reading credentials:

```sh
flux --context apollo get kustomizations -n flux-system
kubectl --context apollo -n storage get helmrelease longhorn
kubectl --context apollo -n storage get pods
kubectl --context apollo -n storage get nodes.longhorn.io
kubectl --context apollo -n storage get nodes.longhorn.io -o yaml
kubectl --context apollo get storageclasses
```

Check all four registered disks across hcc5 through hcc7 are Ready and Schedulable and that no HDD paths appear.
Before moving app data, deploy a disposable PVC and workload through Flux, write a marker, recreate the pod,
and verify the marker survives and the Longhorn volume has three healthy replicas on distinct nodes.
These deployment checks have not yet been performed for this configuration.

The UI is a ClusterIP service; local access uses
`kubectl --context apollo -n storage port-forward service/longhorn-frontend 8080:80`.
No ingress or tailnet identity is claimed. The existing Prometheus stack discovers the chart's ServiceMonitor.

Snapshot-controller, `longhorn-snapclass`, and VolSync follow this step. No cluster-level backup target is
configured; replica redundancy is not an offsite backup. Prometheus and Alertmanager remain on their bootstrap
storage until their separate PVC migration.

## References

Explicit device selection follows the storage patterns in
[szinn](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml)
and [onedr0p](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml).
The five migration reference repos currently use Rook/Ceph rather than Longhorn.
Longhorn's [Talos requirements](https://longhorn.io/docs/1.12.1/advanced-resources/os-distro-specific/talos-linux-support/),
[disk configuration](https://longhorn.io/docs/1.12.1/nodes-and-volumes/nodes/multidisk/), and
[Flux installation](https://longhorn.io/docs/1.12.1/deploy/install/install-with-flux/) supply the product-specific settings.
