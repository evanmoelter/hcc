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

The chart templates its CRDs, so Helm cannot install `longhorn-snapclass` alongside them on a fresh cluster.
Its separate Kustomization waits for the controller. Uninstalling the chart also deletes the snapshot APIs.
Snapshots remain on Longhorn's disks; they are not offsite backups.

## VolSync

The chart's ServiceMonitor supplies no bearer token, so metrics authentication is disabled and a NetworkPolicy
restricts scraping to Prometheus. VolSync, snapshot-controller, and Longhorn scrapes were verified healthy.

The [shared components](../kubernetes/apollo/components/volsync/) keep restore preflight, PVC hydration, and
backups in separate Flux lifecycles. Apps declare their PVCs; the restore component attaches hydration to an
explicitly selected claim after preflight confirms an existing backup. New apps create their claims without
restore configuration. `volsync-test` provides a disposable snapshot → R2 → restored-file verification before app migration.
Its live result remains to be verified; controller and PVC readiness alone do not prove recovered data.

The [OCI mirror](https://github.com/home-operations/charts-mirror) is temporary: switch to upstream OCI when
available, before the mirror's six-month retirement window ends.

## R2 backup separation

| Backup | Old restore source | Apollo write location |
|---|---|---|
| VolSync | `s3://tf-hcc-volsync/<app>` | `s3://tf-hcc-apollo-volsync/<app>` |
| CNPG | `s3://tf-hcc-cloudnativepg/` with the existing server name | `s3://tf-hcc-apollo-cnpg/<app>/` with server name `<app>-pg-apollo-v1` |

Barman appends the server-name directory to the app path. Scope each backup credential to its own bucket,
including old-cluster credentials; paths do not isolate apps sharing a credential. Use separate migration
restore credentials and remove them after verification. Never back up or prune into an old repository.

The operator supplies credentials through 1Password and runs Terraform plan/apply, which decrypts SOPS.
VolSync reads the account ID from the shared `cloudflare-r2` item in `hcc-apollo`; `volsync-r2` holds
shared Apollo VolSync bucket credentials, and app items hold separate restic passwords. [Component usage](../kubernetes/apollo/components/volsync/) lists the fields.
Keep the old bucket resources through rollback: removing their blocks also removes `prevent_destroy` protection.

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
