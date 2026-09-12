# Apollo storage

Longhorn uses the V1 engine. Configuration lives in
[`apps/storage/longhorn`](../kubernetes/apollo/apps/storage/longhorn/).
Storage consumers should depend on `longhorn-config`, which waits for the configured disks to be Ready and Schedulable.

## Storage choices

- `longhorn` is the default StorageClass: three replicas on distinct nodes. `longhorn-two-replicas` is an
  explicit per-app tradeoff. Both classes delete the volume when its PVC is deleted.
- New volumes require enough capacity for every requested replica. Existing volumes can serve with fewer
  replicas during an outage. With three nodes, maintain one at a time and wait for healthy replicas before continuing.
- NVMe user volumes are mounted at `/var/mnt/longhorn`; hcc7 also contributes its SATA SSD at
  `/var/mnt/longhorn-sata`. Both flash types share one pool; the HDDs are excluded because Longhorn ignores disk speed.
- V1 instance managers request 12% of each node's allocatable CPU; account for this when sizing workloads.
- No offsite backup is configured by this component. Replicas alone do not provide one.

## CSI snapshots

Keep snapshot-controller installed while snapshots exist: its chart owns the CRDs as Helm resources,
so uninstalling it deletes the snapshot API objects too. Snapshots stay on Longhorn's disks; offsite
backups await VolSync. A snapshot-and-restore test remains pending before app migration.

## Operations

Change managed disk settings through git; Flux reverts UI edits. Node resources have pruning disabled,
so removing their files does not remove them from Longhorn. Disable scheduling and evacuate replicas before disk removal.

hcc8's disk manifest is prepared but unregistered because Longhorn removes Node resources without a matching
Kubernetes node. When a switch port becomes available:

1. Add hcc8 to [`topf.yaml`](../kubernetes/apollo/bootstrap/talos/topf.yaml) as a worker with its address from
   [networking.md](networking.md) and actual interface MAC. Render with `task talos:render CLUSTER=apollo node=hcc8`,
   then apply with operator approval.
2. Verify the node's Longhorn user volume and kubelet mount, then register `./hcc8.yaml` in
   [`config/kustomization.yaml`](../kubernetes/apollo/apps/storage/longhorn/config/kustomization.yaml).

Access the UI with `kubectl --context apollo -n storage port-forward service/longhorn-frontend 8080:80`.
Before app migration, verify healthy replicas, persistence across pod recreation, and working Prometheus scrapes.
[Boot and disk security](talos-security.md) describes TPM encryption of the Longhorn user volumes and recovery
after node replacement. The [migration plan](../plans/20260816-talos-migration.md) tracks verification, backups,
and remaining storage work.

After recreating a Longhorn filesystem, check `status.diskStatus` on its Longhorn Node resource.
The node summary can report Ready while the disk reports `DiskFilesystemChanged` because its recorded
UUID belongs to the old filesystem. The replacement disk needs re-registration before it is schedulable.
For the empty-disk encryption conversion, clearing only the affected disk's `status.diskStatus.<name>.diskUUID`
through the status subresource lets Longhorn discover the new UUID. Verify there are no volumes, replicas,
or backing images first, and use a JSON Patch test against the old UUID before replacing it with an empty
string. This is an operator-run repair of runtime status; the Git-managed disk specification stays intact.
Do not use this shortcut to adopt a disk when existing data must be recovered.
