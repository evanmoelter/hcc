# Disposable VolSync proof

The normal app is a verifier Job with permanent storage and a separate backup Kustomization.
`ks-fixture.yaml` adds only test setup: a seed PVC/Job and a one-shot backup using the shared backup base.
The chain is **fixture → fixture backup → preflight → storage → app verifier → app backup**.
Both backups are manual-only; the final one backs up the restored claim.

Create the [shared 1Password items](../../../components/volsync/#1password-prerequisites) and a `volsync-test`
item with a new `RESTIC_PASSWORD`. This disposable proof uses that password for both test repositories,
`volsync-test/fixture` and `volsync-test/app`, within `tf-hcc-apollo-volsync`.

## Recovery

After deployment, require all six test Kustomizations to be Ready and the destination to name a ready snapshot.
The verifier must pass checksums, UID/GID, and private-file permission checks using only the restored PVC.
The final backup's `status.lastManualSync` must equal `v1`.

```sh
flux get kustomizations --context apollo
kubectl --context apollo -n storage logs job/volsync-test-verify-v1
kubectl --context apollo -n storage get replicationdestination volsync-test-bootstrap-v1 -o yaml
kubectl --context apollo -n storage get replicationsource volsync-test-r2 -o yaml
```

## Remove restore machinery

Only after recovery and the final backup are verified, apply this prepared change locally, review it, and
commit/merge it through the normal PR workflow:

```sh
git apply tests/fixtures/volsync-test/cleanup.patch
```

It removes preflight and the fixture registration, plus storage's restore component/dependencies and destination
health check. Storage keeps its name and the exact same PVC, including `dataSourceRef`; app and backup remain.
Wait for Flux to apply that commit and prune the temporary resources. Confirm the fixture Kustomizations and
preflight Kustomization, seed Job/PVC, fixture ReplicationSource, preflight Job, restore ExternalSecret/Secret,
ReplicationDestination, and its temporary volumes/snapshot are gone. The app PVC must retain its original UID
and PV binding. Capture those identifiers before cleanup and compare afterward; do not recreate the claim.

## Verify after cleanup

After confirming removal, apply and submit the second prepared change:

```sh
git apply tests/fixtures/volsync-test/verify-cleanup.patch
```

This gives the verifier a new Job name, ensuring it runs again against the same restored PVC after cleanup.
Wait for `volsync-test` to be Ready and inspect its logs:

```sh
kubectl --context apollo -n storage logs job/volsync-test-verify-post-cleanup-v1
```

Keep these as separate deployments so the new verifier cannot run before restore cleanup has completed.
The patches are covered by local/CI render tests; they perform no live mutations themselves.

## Teardown

After the second verification, remove the remaining two registrations (`ks.yaml` and `ks-storage.yaml`) and the
test directory in a follow-up commit. Flux prunes the remaining disposable resources and PVC. Remove the patch
fixtures and lifecycle test with it. The operator removes both R2 test paths and the `volsync-test` 1Password
item separately, keeping the shared credential items. A fresh full proof needs new app/repository names.
