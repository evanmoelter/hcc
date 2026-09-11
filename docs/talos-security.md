# Apollo boot and disk security

Apollo uses SideroLabs-signed Secure Boot images and TPM-backed LUKS2 encryption. `secureboot: true` in
[`topf.yaml`](../kubernetes/apollo/bootstrap/talos/topf.yaml) selects the signed installer for installs and upgrades.

| Encrypted volume | Nodes | Bound to STATE |
|---|---|---|
| STATE | all | no |
| EPHEMERAL | all | yes |
| longhorn | all | yes |
| longhorn-sata | hcc7 | yes |

Keys use TPM PCR 7 and signed PCR 11 policy, with no password or KMS fallback. TPM loss or clearing
requires rebuilding the node and restoring from replicas or backups. Replacing STATE also makes its
bound volumes unreadable. Firmware and Secure Boot key/database changes can prevent TPM unlocking.

All three nodes passed an unattended reboot with USB removed. All ten encrypted volumes, three etcd
members, and four Longhorn disks were healthy afterward.

## Reprovisioning

1. Preserve the existing Talos secrets and bootstrap credentials; see [secrets.md](secrets.md) and
   [certificate recovery](certificates.md#cluster-rebuilds).
2. Render with `task talos:render CLUSTER=apollo`. Boot `metal-amd64-secureboot.iso` for the version and
   schematic in `topf.yaml`, enable TPM/PTT, and enroll SideroLabs keys from the boot menu.
3. Confirm disk identities before wiping. Recreate all encrypted volumes, including hcc7's SATA volume;
   leave hcc5/hcc6's unused HDDs alone. FAST wipes clear metadata but do not sanitize old plaintext.
4. Apply the node's rendered config. A replacement rejoins surviving etcd members without bootstrapping.
   [Storage operations](storage.md#operations) covers stale Longhorn disk UUIDs after reprovisioning.
5. Remove USB, test another unattended reboot, and verify Secure Boot, encrypted volumes, etcd health,
   and Longhorn disk readiness before continuing to another node.

Run live mutations as the operator. Use `get securitystate -o yaml` and `get volumestatus -o yaml`
through the authenticated Talos API to verify `secureBoot: true`, ready LUKS2 volumes, the TPM policy,
and STATE binding on non-STATE volumes. A full rebuild requires verified backups once apps hold data.

See Talos's [Secure Boot guide](https://docs.siderolabs.com/talos/v1.13/platform-specific-installations/bare-metal-platforms/secureboot)
and [encryption guide](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-encryption)
for detailed procedures.
