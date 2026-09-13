# VolSync components

The [disposable test](../../apps/storage/volsync-test/) is a complete example. Attach components through
Flux `spec.components`, relative to the owner's `spec.path`, with these dependencies:

| Component | Depends on |
|---|---|
| `volsync/restore-preflight` | `onepassword-store`; use `wait: true` for the repository check. |
| `volsync/restore` | Preflight, `volsync`, and `longhorn-config`; use `wait: true`. |
| `volsync/backup` | Serving app, `volsync`, and `onepassword-store`. |

Apps own their PVC manifests and depend on their storage/restore Kustomization. Label exactly one recovery
claim `volsync.home.arpa/restore: "true"` to attach its `dataSourceRef`. Copy **both** readiness expressions
from the test's `ks-restore.yaml`, adapting the expected PVC and destination names to the app and restore ID.
They block the app when the restore is incomplete or its PVC lacks the expected reference, even if Bound.
A mistakenly provisioned empty PVC must be recreated before recovery; adding a reference cannot hydrate it.
New apps explicitly create a plain PVC without restore components. Protect durable claims with
`kustomize.toolkit.fluxcd.io/prune: disabled`; the disposable test omits it.

Set `APP` for each backup stream. Backup `CLAIM` and repository paths default to `APP`.
Restore requires `VOLSYNC_RESTORE_ID` on both owners, `VOLSYNC_RESTORE_BUCKET` on preflight, and
`VOLSYNC_CAPACITY` matching the app claim. A claim smaller than the restore snapshot fails provisioning.
`VOLSYNC_STORAGECLASS` must support the same CSI snapshot driver as the claim; size `VOLSYNC_CACHE_CAPACITY`
for the repository's metadata. Use a fresh restore ID and update the readiness expression for every recovery
attempt, including after changing credentials/source or correcting a failed preflight. Do not add Job TTLs:
Flux would recreate completed Jobs indefinitely.

[Upstream](https://github.com/backube/volsync/blob/v0.16.0/mover-restic/entry.sh) accepts empty repositories
as successful restores. Preflight requires an existing snapshot for host `volsync` and path `/data`, without
initializing or locking the repository. It checks once; keep the source backup/prune writer stopped during
migration, then verify application data before enabling traffic and Apollo backups. Recovery uses the latest backup.

## 1Password prerequisites

The operator creates these items in `hcc-apollo`; ESO maps the R2 fields to restic's required `AWS_*` keys.

| Item | Fields |
|---|---|
| `cloudflare-r2` | `ACCOUNT_ID`, shared to construct the private endpoint. |
| `volsync-r2` | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`; Object Read & Write on `tf-hcc-apollo-volsync` only. |
| App name (`APP`) | `RESTIC_PASSWORD`, unique per repository. Use `volsync-test` for the disposable proof. |

Override the shared key item with `VOLSYNC_R2_CREDENTIALS_ITEM` (backup) or
`VOLSYNC_RESTORE_R2_CREDENTIALS_ITEM` (restore). Override the password item with `VOLSYNC_CREDENTIALS_ITEM`
or `VOLSYNC_RESTORE_CREDENTIALS_ITEM`, respectively. Bucket names and paths stay in git.

Backups always write to `tf-hcc-apollo-volsync`. For migration, set `VOLSYNC_RESTORE_BUCKET` and
`VOLSYNC_RESTORE_PATH` to the old repository, and override both restore credential items for its scoped R2
key and original restic password (one item can hold all three fields). The mover writes repository locks,
so restore also needs Object Read & Write; revoke the old-bucket key after verification. After a verified
Apollo backup, point future restores at Apollo's repository and credentials.

## Disposable proof

After merge, require all five `volsync-test-*` Flux Kustomizations to be Ready, inspect the verifier Job logs,
and confirm the destination names a ready CSI snapshot. The test seeds two files, backs up once, restores
into a separate PVC, and verifies checksums, ownership, and private-file permissions using only that PVC.
This proves fixture recovery; application consistency still needs its own verification.

Remove the five registrations after verification; Flux prunes the disposable resources and PVCs. The operator
removes the R2 test path and `volsync-test` 1Password item separately, keeping the shared credential items.
For another full proof, use a fresh app name and repository path.
