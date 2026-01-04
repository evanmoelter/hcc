# Plan: Blacklist Longhorn Devices from Multipath

## Overview

Configure multipath to ignore Longhorn iSCSI devices, preventing multipath from claiming block devices that should be managed directly by the Longhorn CSI driver.

## Problem

Longhorn exposes storage via iSCSI. The multipath daemon can incorrectly claim these devices, creating device-mapper entries (`mpatha`, `mpathb`, etc.) that block the CSI driver from mounting volumes directly. This causes pods to get stuck in `ContainerCreating` with mount errors like:

```
mount: /dev/longhorn/pvc-xxx already mounted or mount point busy
```

## Root Cause

From `multipath -ll` output, Longhorn devices appear as:
```
mpatha (360000000000000000e00000000010001) dm-2 IET,VIRTUAL-DISK
```

- **Vendor:** `IET` (iSCSI Enterprise Target)
- **Product:** `VIRTUAL-DISK`

## Current State

Minimal multipath config on nodes:
```
defaults {
    user_friendly_names yes
}
```

No blacklist rules exist, so multipath claims any device it discovers.

## Target State

Multipath ignores all Longhorn/IET iSCSI devices via a device blacklist.

## Implementation Steps

### Step 1: Create multipath blacklist config

Create `/etc/multipath/conf.d/longhorn-blacklist.conf` on all nodes:

```conf
blacklist {
    device {
        vendor "IET"
        product "VIRTUAL-DISK"
    }
}
```

### Step 2: Apply via Ansible

Add to your Ansible node configuration playbook:

```yaml
- name: Create multipath conf.d directory
  file:
    path: /etc/multipath/conf.d
    state: directory
    mode: '0755'

- name: Blacklist Longhorn devices from multipath
  copy:
    dest: /etc/multipath/conf.d/longhorn-blacklist.conf
    content: |
      blacklist {
          device {
              vendor "IET"
              product "VIRTUAL-DISK"
          }
      }
    mode: '0644'
  notify: Reload multipathd
```

Add handler:
```yaml
handlers:
  - name: Reload multipathd
    systemd:
      name: multipathd
      state: reloaded
```

### Step 3: Manual application (if needed immediately)

Run on each node:
```bash
sudo mkdir -p /etc/multipath/conf.d
sudo tee /etc/multipath/conf.d/longhorn-blacklist.conf << 'EOF'
blacklist {
    device {
        vendor "IET"
        product "VIRTUAL-DISK"
    }
}
EOF
sudo systemctl reload multipathd
```

### Step 4: Verify configuration

Check blacklist is loaded:
```bash
sudo multipath -t | grep -A5 blacklist
```

Verify no Longhorn devices are claimed:
```bash
sudo multipath -ll
```

Should return empty or only show non-Longhorn devices.

## Alternative: Disable multipath entirely

If you don't use multipath for any storage, you can disable it:

```bash
sudo systemctl stop multipathd
sudo systemctl disable multipathd
```

## Nodes Affected

All k3s worker nodes that run Longhorn:
- hcc1
- hcc2
- hcc3
- hcc4
- hcc5

## k3s Compatibility

Fully compatible - this is a host-level multipath configuration change.

## Testing

1. Apply config to one node (e.g., hcc3)
2. Reload multipathd: `sudo systemctl reload multipathd`
3. Verify no multipath devices: `sudo multipath -ll`
4. Trigger a volsync backup or attach a Longhorn volume
5. Confirm mount succeeds without multipath interference
6. Roll out to remaining nodes

## Recovery Steps

If a volume gets stuck due to multipath before the fix is applied:

```bash
# Identify the multipath device
sudo multipath -ll

# Flush the multipath device
sudo multipath -f mpathX

# Delete the stuck pod to trigger remount
kubectl delete pod <stuck-pod> --force --grace-period=0
```

## Dependencies

None - can be implemented independently.

## Benefits

- Prevents Longhorn mount failures from multipath interference
- No impact on legitimate multipath SAN devices (if any)
- Survives reboots once applied

