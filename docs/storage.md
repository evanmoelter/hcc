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
so uninstalling it deletes the snapshot API objects too. `snapshot-controller-config` creates
`longhorn-snapclass` only after the controller is ready. Rendering the class in the chart's first install
fails because Helm cannot discover the snapshot API before the templated CRDs exist.
Snapshots stay on Longhorn's disks. A snapshot-and-restore test remains pending before app migration.

## VolSync

The VolSync controller waits for `snapshot-controller-config` and bootstrap monitoring. Its upstream chart
pins the controller and all mover images to the chart's application version. Apollo uses upstream restic;
the old cluster's custom image is not carried forward. The controller runs as UID/GID 568; each future
ReplicationSource and ReplicationDestination must set its mover ownership to match the application volume.

The chart creates an HTTPS ServiceMonitor when the Prometheus CRDs are available. Metrics authentication
is disabled because that monitor supplies no bearer token; a NetworkPolicy restricts controller ingress
to Prometheus in `monitoring` on port 8443. The monitor accepts the controller's self-signed certificate.
Prometheus rules report missing or unreachable metrics and out-of-sync volumes.

Controller installation does not create backup jobs or repository credentials. Before the first PVC-backed
app moves, add the planned reusable `volsync` component, with a one-time restore destination and hydrating
claim plus a separately reconciled backup source. ESO should provide separate restore and backup Secrets
using the bucket separation below. The operator supplies the existing repository password and R2 credentials
through 1Password. Never run an Apollo backup or prune against the old repository.

After deployment, verify `snapshot-controller`, `snapshot-controller-config`, and `volsync` are Ready,
`longhorn-snapclass` exists, and Prometheus can scrape `volsync-metrics`. Before app migration, exercise a
Longhorn snapshot restore, then a restic backup and one-time PVC restore using disposable data in an
Apollo-only repository. Check file contents and ownership. Those tests and the shared component remain pending.

The controller monitoring pattern draws from
[onedr0p's historical VolSync release](https://github.com/onedr0p/home-ops/blob/63c93686994429bcd2c283a5963decec7fe5441d/kubernetes/apps/volsync-system/volsync/app/helmrelease.yaml)
and [joryirving's historical release](https://github.com/joryirving/home-ops/blob/0c1279556bf9638781b6936597f8f2dbcb6e9ffc/kubernetes/apps/base/storage/volsync/helmrelease.yaml).
Their mover forks are not the migration backend. See the
[upstream permission model](https://volsync.readthedocs.io/en/stable/usage/permissionmodel.html) for mover ownership.

## R2 backup separation

Each cluster has separate VolSync and CNPG buckets, with paths per app. Terraform owns Apollo's buckets in
[`apollo-backups.tf`](../terraform/cloudflare/apollo-backups.tf); the old buckets retain their existing names.

| Backup | Old restore source | Apollo write location |
|---|---|---|
| VolSync | `s3://tf-hcc-volsync/<app>` | `s3://tf-hcc-apollo-volsync/<app>` |
| CNPG | `s3://tf-hcc-cloudnativepg/` with the existing server name | `s3://tf-hcc-apollo-cnpg/<app>/` with server name `<app>-pg-apollo-v1` |

For CNPG, the app path is the ObjectStore's `destinationPath`; Barman appends the server-name directory.
Source ObjectStores keep the old path and server name for recovery.

Use separate Object Read & Write credentials for the two Apollo buckets, each scoped to its own bucket.
Restrict old-cluster runtime credentials to the old buckets too; an all-buckets token would defeat this
separation. R2's regular tokens enforce permissions at the
[bucket boundary](https://developers.cloudflare.com/r2/api/tokens/), so app paths organize repositories
but do not isolate apps sharing a bucket credential. Keep migration restore credentials separate from
Apollo's backup credentials and remove them after the restores are verified.

The operator creates the scoped credentials in 1Password for ESO to consume. Terraform plan and apply are
also operator steps: this stack decrypts its existing SOPS datasource. Review the plan for the two added
buckets before applying; existing backup buckets and objects must remain intact.

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
