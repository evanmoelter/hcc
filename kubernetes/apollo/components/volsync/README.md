# VolSync

PVC-backed apps use this layout:

```text
app-name/
  ks.yaml          app Kustomization
  ks-storage.yaml  preflight, storage, and backup Kustomizations (separate YAML documents)
  app/             workload manifests
  storage/         app-owned PVC manifests
```

Name the restore preflight Kustomization `<app>-restore-preflight` to distinguish it from app-specific checks.
Preflight and backup point `spec.path` directly at the shared `volsync/restore-preflight` and `volsync/backup`
bases here. Storage includes `volsync/restore` through `spec.components` only during recovery.
The ordering is **preflight → storage → app → backup**. Preflight needs `onepassword-store`; storage needs
`longhorn-config` and, during recovery, `volsync`; backup needs `volsync` and `onepassword-store`.
Use `wait: true` and adapt the PVC/destination names in the
[verified proof's storage readiness expressions](https://github.com/evanmoelter/hcc/blob/ae99787081248ec0a513bd5d70fe32804c9c9849/kubernetes/apollo/apps/storage/volsync-test/ks-storage.yaml).

Apps declare the PVC's `dataSourceRef` explicitly for recovery. A new app instead creates a plain PVC and
omits preflight and the restore component. Protect durable claims with
`kustomize.toolkit.fluxcd.io/prune: disabled`.

Set `APP` for each backup stream; backup `CLAIM` and repository paths default to `APP`.
Recovery requires `VOLSYNC_RESTORE_ID` on preflight and storage, `VOLSYNC_RESTORE_BUCKET` on preflight,
and `VOLSYNC_CAPACITY` matching the claim. A claim smaller than the restore snapshot fails provisioning.
`VOLSYNC_STORAGECLASS` must support the claim's CSI snapshot driver; size `VOLSYNC_CACHE_CAPACITY` for
repository metadata. The PVC reference and readiness expression must name the destination for that restore ID.

## Restore lifecycle

[Upstream](https://github.com/backube/volsync/blob/v0.16.0/mover-restic/entry.sh) accepts an empty repository
as a successful restore. Preflight requires an existing snapshot for host `volsync` and path `/data`, without
initializing or locking the repository. Keep source backup/prune writers stopped during migration and verify
application data before enabling traffic and Apollo backups. Recovery uses the latest backup.

The restore keeps its temporary data PVC until cleanup. Longhorn needs that volume while cloning the local
snapshot into the app PVC; deleting it when the restic mover finishes can strand the clone
([upstream report](https://github.com/backube/volsync/issues/1504)). Allow capacity for both volumes until the
app can mount and verify its data. The restic cache can be removed immediately.

After data verification and the first Apollo backup, make a cleanup commit: remove preflight, the storage
restore component, and storage's preflight/VolSync dependencies and destination health check. Keep the same
storage Kustomization, PVC manifest, and PVC readiness check. Flux prunes the temporary destination and
restore credentials; deleting the destination also garbage-collects its retained temporary PVC.
Preserve the PVC's immutable `dataSourceRef` exactly; it remains valid on the bound PVC.
With its destination gone, a newly provisioned replacement claim blocks until recovery is explicitly configured.

A future recovery requires a new ID, source/credentials, fresh preflight, and an explicitly provisioned replacement
PVC; changing a bound PVC's reference cannot restore it. Failed attempts also need a new ID after diagnosis.
Manual triggers prevent recurring restores while their completion status exists, but recreating a destination can
repeat them: complete cleanup after verification. Do not add Job TTLs; Flux would recreate completed Jobs.

## 1Password prerequisites

The operator creates these items in `hcc-apollo`; ESO maps R2 fields to restic's required `AWS_*` keys.

| Item | Fields |
|---|---|
| `cloudflare-r2` | `ACCOUNT_ID`, shared to construct the private endpoint. |
| `volsync-r2` | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`; Object Read & Write on `tf-hcc-apollo-volsync` only. |
| App name (`APP`) | `RESTIC_PASSWORD`, unique per app repository. |

Override key items with `VOLSYNC_R2_CREDENTIALS_ITEM` or `VOLSYNC_RESTORE_R2_CREDENTIALS_ITEM`;
override password items with `VOLSYNC_CREDENTIALS_ITEM` or `VOLSYNC_RESTORE_CREDENTIALS_ITEM`.
Backups always write to Apollo's bucket. For migration, set `VOLSYNC_RESTORE_BUCKET` and
`VOLSYNC_RESTORE_PATH` to the old repository and override both restore credential items for its scoped R2 key
and original restic password (one item may hold all three fields). Restore needs Object Read & Write for locks;
revoke the old-bucket key after verification. Bucket names and paths stay in git.

The disposable live proof is complete; [storage documentation](../../../../docs/storage.md#volsync) records its result.
