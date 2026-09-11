# Apollo boot and disk security

Apollo uses SideroLabs-signed Secure Boot images and TPM-backed LUKS2
encryption. `secureboot: true` in `topf.yaml` selects `metal-installer-secureboot` for installation and
subsequent topf upgrades. The schematic retains the existing extensions.

All three nodes passed Secure Boot and TPM encryption verification and an additional unattended reboot
with USB media removed. All ten encrypted volumes were Ready with PCR 7 and signed PCR 11 policies;
non-STATE volumes were bound to STATE, with no failed key syncs. The existing etcd cluster was retained.

| Volume | Nodes | Bound to STATE |
|---|---|---|
| STATE | all | no |
| EPHEMERAL | all | yes |
| longhorn | all | yes |
| longhorn-sata | hcc7 | yes |

Each volume has one TPM key slot. The default TPM policy binds Secure Boot state through PCR 7 and
the signed boot measurements through PCR 11. There is no static password, node-ID fallback, or KMS.
TPM loss or clearing requires rebuilding the affected node and recovering workloads from surviving
replicas or backups. Replacing STATE also makes its bound volumes unreadable. Before firmware or
Secure Boot key/database changes, account for the possibility that the TPM will refuse to unlock.
Ordinary Talos upgrades must continue using the signed installer and compatible signing keys.

Encryption covers these writable volumes; it does not encrypt every boot partition. Existing filesystem
data is not encrypted in place. A normal reset or FAST wipe is not an overwrite of old plaintext.

## Conversion runbook

Convert hcc5 first, then hcc6, then hcc7. Availability is not a requirement during this conversion;
re-bootstrap is the fallback if retaining the existing cluster becomes more work than rebuilding it.
These instructions assume no household apps or PVCs have arrived. Recheck before any wipe.
Every live mutation below requires explicit operator approval for the named node and disks.

### Prepare

The operator must have console/BIOS access, bootable USB media, and access to the existing Talos secrets,
age key, Flux source credentials, and Connect credentials if fallback bootstrap is needed. Preserve
the existing Talos secrets bundle so a replacement node can join the existing cluster. Do not regenerate it.
For a full rebuild, account for the certificate and ACME state described in [certificates.md](certificates.md).

Render the configurations and derive the ISO URL from the same version and schematic:

```sh
task talos:render CLUSTER=apollo
TALOS_DIR=kubernetes/apollo/bootstrap/talos
TALOS_VERSION=$(yq '.talosVersion' "$TALOS_DIR/topf.yaml")
SCHEMATIC_ID=$(topf --topfconfig "$TALOS_DIR/topf.yaml" --nodes-filter '^hcc5$' schematic-ids)
mkdir -p .private/apollo-secureboot
curl --fail --location \
  "https://factory.talos.dev/image/$SCHEMATIC_ID/$TALOS_VERSION/metal-amd64-secureboot.iso" \
  --output .private/apollo-secureboot/metal-amd64-secureboot.iso
```

The operator writes the ISO to USB. Rendered configs contain credentials: keep them in the ignored
`rendered/` directory and never print, commit, or share them.

Set the target for one conversion. Use its direct address as the Talos endpoint:

```sh
TALOS_NODE=hcc5
TALOS_NODE_IP=192.168.21.5
export TALOSCONFIG="$PWD/kubernetes/apollo/bootstrap/talos/talosconfig"
kubectl --context apollo get nodes
kubectl --context apollo get pvc -A
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" etcd members
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" get disks
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" get volumestatus
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" read /sys/class/tpm/tpm0/tpm_version_major
```

Require TPM version 2. Confirm the system disk by its volume locations and physical identity.
hcc5 and hcc6 each have an excluded 1 TB SATA HDD; leave those disks alone. hcc7's second Longhorn
volume is on its Samsung SATA SSD. Recheck device names after booting USB, since enumeration can change.

### Reset and boot signed media

After approval, gracefully leave etcd, wipe only the system disk, and power off this node:

```sh
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" reset \
  --graceful=true --wipe-mode=system-disk --reboot=false
```

This removes STATE, EPHEMERAL, and the NVMe Longhorn volume. Use this explicit command for conversion:
the general `task talos:reset` waits for maintenance and does not restrict the default wipe scope.
Do not apply the encryption configuration to the old running installation or use upgrade as the conversion step.

In BIOS, enable TPM/PTT and UEFI Secure Boot, placing firmware in setup mode for key enrollment.
Boot the Secure Boot USB, press Esc for the boot menu, and select `Enroll Secure Boot keys: auto`.
Bare-metal enrollment requires this manual step. Check the console's maintenance IP; it may differ
from the configured node IP because the machine configuration has been wiped.

```sh
TALOS_MAINTENANCE_IP=<address-from-console>
talosctl -n "$TALOS_MAINTENANCE_IP" get securitystate --insecure -o yaml
talosctl -n "$TALOS_MAINTENANCE_IP" get disks --insecure
```

Require `secureBoot: true` and `bootedWithUKI: true` before installing. Confirm the disk identities again.
Clear old filesystem metadata with a FAST wipe of the identified NVMe. On hcc7, include the identified
SATA SSD; it still contains the old Longhorn filesystem.
These commands assume the inventory confirms the shown names:

```sh
talosctl -n "$TALOS_MAINTENANCE_IP" wipe disk nvme0n1 --insecure --method FAST
```

hcc7 only:

```sh
talosctl -n "$TALOS_MAINTENANCE_IP" wipe disk sda --insecure --method FAST
```

FAST prepares the disk for encrypted provisioning without overwriting every block. The operator accepts
possible historical plaintext remnants for this same-cluster reuse. Encryption protects subsequent writes;
it does not sanitize earlier data. Wait for completion before installation.

### Install and verify

After approval, send this node's rendered configuration to its maintenance address:

```sh
talosctl -n "$TALOS_MAINTENANCE_IP" apply-config --insecure \
  --file "kubernetes/apollo/bootstrap/talos/rendered/$TALOS_NODE.yaml"
```

Remove the USB for the installed-system boot. The node rejoins the existing cluster; do not run
`talosctl bootstrap` during rolling conversion.

```sh
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" get securitystate -o yaml
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" get volumestatus -o yaml
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" etcd members
kubectl --context apollo get nodes
talosctl -e "$TALOS_NODE_IP" -n 192.168.21.5,192.168.21.6,192.168.21.7 service etcd
kubectl --context apollo -n storage get nodes.longhorn.io
flux --context apollo get kustomizations -A
```

Require Secure Boot and UKI, and ready encrypted volumes `STATE`, `EPHEMERAL`, `u-longhorn`, plus
`u-longhorn-sata` on hcc7. Volume status must report `encryptionProvider: luks2`, TPM PCR 7 and signed
PCR 11 policy, and `encryptionLockedToState: true` for non-STATE volumes, with no failed key syncs.
Confirm Longhorn recognizes the recreated disks as Ready and Schedulable. The verified repair for stale
disk UUIDs after this conversion is described in [storage.md](storage.md).

After approval, test an additional unattended reboot with USB removed:

```sh
talosctl -e "$TALOS_NODE_IP" -n "$TALOS_NODE_IP" reboot
```

Repeat the security, volume, etcd, and readiness checks after reboot. Require all nodes Ready and etcd
running and healthy on each node; membership alone does not prove health. Restore three etcd members before
starting the next conversion; if that becomes impractical, explicitly switch to the rebuild fallback.
Record the verified result for each node before marking the migration security gate complete.

## Full rebuild fallback

Fallback is a separate destructive operation requiring approval. Account for bootstrap credentials and
certificate state first. Reinstall all nodes with the signed media and encrypted configuration, bootstrap
etcd exactly once, refresh the Apollo kubeconfig with `task talos:kubeconfig CLUSTER=apollo`, and run
`task bootstrap:cluster CLUSTER=apollo` after approval. Let Flux restore platform services from git.
Repeat the encryption and unattended-reboot checks on every node. A full rebuild also discards any
Longhorn data; once apps arrive, recovery requires verified offsite backups.

## References

- [Talos Secure Boot](https://docs.siderolabs.com/talos/v1.13/platform-specific-installations/bare-metal-platforms/secureboot)
- [Talos disk encryption](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-encryption)
- [Talos CLI](https://docs.siderolabs.com/talos/v1.13/reference/cli)
- [topf installer configuration](https://github.com/postfinance/topf/blob/v0.5.0/docs/configuration.md)

