# Authentik RWX rehearsal

Apollo's first RWX consumer needs live verification before merge. This fixture is outside the Flux tree
and contains only disposable resources. Rendering it does not contact or change the cluster:

```sh
python3 tests/fixtures/authentik-rwx/rehearse.py > /tmp/authentik-rwx-proof.json
```

With explicit operator approval, run:

```sh
python3 tests/fixtures/authentik-rwx/rehearse.py --run --context apollo
```

The script creates a new `authentik-rwx-proof` namespace; it refuses to reuse an existing namespace.
It creates three 1 GiB Longhorn claims, two CSI snapshots, and five pods using the pinned Authentik image.
All pods run as UID/GID 568 with a read-only root filesystem and no API token. It checks:

1. Pods on hcc5 and hcc6 can write and read the same fresh RWX claim, including the backup seed file.
2. An RWO clone of the RWX snapshot preserves the files and can be read by UID 568, matching the
   VolSync backup mover's access mode and security context.
3. A snapshot of that RWO volume provisions a replacement RWX claim. Pods on both nodes verify the
   restored contents and can write new files, covering the shared restore component's mode transition.

Longhorn's CSI policy on Apollo is `ReadWriteOnceWithFSType`, so kubelet fsGroup ownership changes
cannot be assumed for RWX. The pinned share-manager instead
[sets the export root to 0777](https://github.com/longhorn/longhorn-share-manager/blob/v1.12.1/pkg/server/share_manager.go#L172).
The rehearsal checks actual NFS access without adding root permission-fixing containers or changing
the cluster-wide CSI policy.

The script removes its namespace after success, including its PVCs and snapshots. It requires a
snapshot class with deletion policy `Delete`. On failure it retains resources for diagnosis. Inspect
only this namespace, then remove it with operator approval:

```sh
kubectl --context apollo -n authentik-rwx-proof get pods,pvc,volumesnapshots
kubectl --context apollo delete namespace authentik-rwx-proof
```

This does not run Restic, access R2, or exercise the VolSync controller. A successful first application
backup remains a separate deployment gate in [identity documentation](../../../docs/identity.md#file-backup-and-recovery).
## Execution record

On 2026-09-30, this rehearsal ran with operator approval on Apollo with Longhorn 1.12.1 and the
pinned Authentik 2026.8.3 image. All five pods became Ready with UID/GID 568:

- Fresh RWX clients on hcc5/hcc6 created the seed and shared private-mode files without permission fixes.
- The RWO snapshot clone preserved both clients' file contents and accepted a new marker.
- The replacement RWX claim preserved all markers; clients on hcc5/hcc6 read and wrote it successfully.

Both snapshots became ReadyToUse. The clone clients briefly reported `FailedAttachVolume` while
Longhorn copied data; retries converged without intervention. The script then deleted its isolated namespace.
