# Plan: Multus CNI Setup (Prerequisite for IoT Network Access)

## Overview

Install Multus CNI to enable pods to attach to multiple networks. This is required for Home Assistant (and other home automation apps) to have direct Layer 2 access to IoT devices for protocols like mDNS, CoIoT, and HomeKit.

## Network Context

- **Network hardware**: Ubiquiti UniFi
- **VLANs**: Two configured - normal devices and IoT
- **Cluster location**: Already on the IoT VLAN

Since the cluster nodes are already on the IoT VLAN, pods *can* reach IoT devices via Cilium's NAT (outbound works). However, **Multus is still needed for**:
- **mDNS/multicast** - Discovery protocols like Bonjour, CoIoT, Shelly don't work through NAT
- **Bidirectional L2** - Some integrations need devices to initiate connections to HA
- **HomeKit** - Requires mDNS for device pairing

## Problem

Even though the cluster is on the IoT VLAN, Kubernetes pods use the Cilium overlay network:
- Outbound traffic is NATed through the node
- Multicast/broadcast doesn't cross the NAT boundary
- IoT devices can't initiate connections to pods

## Solution

Multus CNI allows pods to have multiple network interfaces:
1. Primary interface: Standard cluster network (CNI - Cilium)
2. Secondary interface: Direct macvlan attachment to the IoT network

## Architecture

```
Pod (e.g., Home Assistant)
├── eth0 (Cilium CNI) - Cluster network (10.42.x.x)
└── net1 (macvlan) - IoT network (same subnet as nodes)
```

## Prerequisites

- Identify the host interface name on worker nodes (typically `eth0` or `ens18`)
- Reserve a static IP for Home Assistant on the IoT network (outside DHCP range)

## Implementation Steps

### Step 1: Create Directory Structure

```bash
mkdir -p kubernetes/main/apps/kube-system/multus/app
```

### Step 2: Create Flux Kustomization

Create `kubernetes/main/apps/kube-system/multus/ks.yaml`:

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app multus
  namespace: flux-system
spec:
  targetNamespace: kube-system
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  path: ./kubernetes/main/apps/kube-system/multus/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: true
  interval: 30m
  retryInterval: 1m
  timeout: 5m
```

### Step 3: Create App Kustomization

Create `kubernetes/main/apps/kube-system/multus/app/kustomization.yaml`:

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  - ./network-attachment-definition.yaml
```

### Step 4: Create HelmRelease

Create `kubernetes/main/apps/kube-system/multus/app/helmrelease.yaml`:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: multus
  namespace: kube-system
spec:
  interval: 30m
  chart:
    spec:
      chart: multus
      version: 5.0.7
      sourceRef:
        kind: HelmRepository
        name: angelnu
        namespace: flux-system
  values:
    image:
      repository: ghcr.io/k8snetworkplumbingwg/multus-cni
      tag: v4.1.2-thick

    cni:
      # Path where k3s stores CNI configs
      paths:
        config: /var/lib/rancher/k3s/agent/etc/cni/net.d
        bin: /var/lib/rancher/k3s/data/current/bin

    # Resources
    resources:
      requests:
        cpu: 10m
        memory: 64Mi
      limits:
        memory: 128Mi

    # Run on all nodes including control plane
    tolerations:
      - operator: Exists
```

**Note**: You may need to add the angelnu Helm repository if not already present:

```yaml
# In kubernetes/main/flux/repositories/helm/angelnu.yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: angelnu
  namespace: flux-system
spec:
  interval: 2h
  url: https://angelnu.github.io/helm-charts
```

### Step 5: Create Network Attachment Definition

Create `kubernetes/main/apps/kube-system/multus/app/network-attachment-definition.yaml`:

```yaml
---
# IoT Network - for Home Assistant, ESPHome, etc.
# Since the cluster is already on the IoT VLAN, no VLAN tagging is needed.
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: iot
  namespace: kube-system
spec:
  config: |
    {
      "cniVersion": "0.3.1",
      "name": "iot",
      "type": "macvlan",
      "master": "eth0",
      "mode": "bridge",
      "ipam": {
        "type": "static"
      }
    }
```

**Note**: Adjust `master` if your nodes use a different interface name (e.g., `ens18`, `enp0s3`). Check with:
```bash
kubectl get nodes -o wide  # Look at INTERNAL-IP
ssh <node> ip link show    # Find the interface with that IP
```

### Ubiquiti Compatibility

UniFi switches work well with macvlan - no special configuration needed.

If mDNS discovery doesn't work after setup, check these UniFi settings:
- **Network > Settings > Multicast DNS**: Should be enabled
- **IGMP Snooping**: If enabled, ensure mDNS traffic isn't being filtered

### Step 6: Register with kube-system Kustomization

Add to `kubernetes/main/apps/kube-system/kustomization.yaml`:

```yaml
resources:
  # ... existing resources
  - ./multus/ks.yaml
```

### Step 7: Using Multus in Pods

Once installed, pods can request additional network interfaces via annotations:

```yaml
# In a pod spec or HelmRelease values
pod:
  annotations:
    k8s.v1.cni.cncf.io/networks: |
      [{
        "name": "iot",
        "namespace": "kube-system",
        "ips": ["192.168.x.100/24"]
      }]
```

For Home Assistant specifically (update the helmrelease.yaml):

```yaml
controllers:
  home-assistant:
    pod:
      annotations:
        k8s.v1.cni.cncf.io/networks: |
          [{
            "name": "iot",
            "namespace": "kube-system",
            "ips": ["192.168.x.100/24"]
          }]
```

**Important**: Replace `192.168.x.100/24` with an IP on your IoT subnet that is:
- Outside the DHCP range (to avoid conflicts)
- Reserved in UniFi for Home Assistant (optional but recommended)

## Network Configuration Considerations

### Why macvlan?

Since UniFi switches handle macvlan well, it's the recommended choice:
- Each pod gets a unique MAC address on the IoT network
- Full L2 connectivity including multicast
- No special switch configuration needed

**Note**: One limitation of macvlan is that the host cannot communicate with the pod via the macvlan interface. This is fine since the pod still has its primary Cilium interface for cluster traffic.

### IP Address Management

Using static IPs (shown above) is recommended for Home Assistant because:
- IoT devices can reliably find HA at a known address
- mDNS announcements use a consistent IP
- Easier to create firewall rules if needed

Reserve the IP in UniFi (Network > Client Devices > Add Client) to document it even though it's not DHCP-assigned.

## Verification

After deployment:

1. Check Multus is running:
   ```bash
   kubectl get pods -n kube-system -l app=multus
   ```

2. Check NetworkAttachmentDefinition exists:
   ```bash
   kubectl get net-attach-def -A
   ```

3. Test with a debug pod (replace IP with one on your IoT subnet):
   ```yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: multus-test
     namespace: default
     annotations:
       k8s.v1.cni.cncf.io/networks: |
         [{"name": "iot", "namespace": "kube-system", "ips": ["192.168.x.250/24"]}]
   spec:
     containers:
       - name: test
         image: nicolaka/netshoot
         command: ["sleep", "infinity"]
   ```

4. Verify multiple interfaces:
   ```bash
   kubectl exec multus-test -- ip addr
   # Should show eth0 (cluster network) and net1 (IoT network)
   ```

5. Test IoT network connectivity:
   ```bash
   # Ping your IoT gateway
   kubectl exec multus-test -- ping -c 3 192.168.x.1

   # Test mDNS (should see IoT devices advertising)
   kubectl exec multus-test -- avahi-browse -a -t
   ```

6. Clean up test pod:
   ```bash
   kubectl delete pod multus-test
   ```

## Rollback Plan

If Multus causes networking issues:

1. Remove pod annotations using Multus networks
2. Delete the Flux Kustomization:
   ```bash
   kubectl delete kustomization multus -n flux-system
   ```
3. Multus is non-destructive - removing it doesn't affect the primary CNI

## k3s Compatibility

Fully compatible with k3s. Key considerations:
- CNI paths are different from standard Kubernetes (handled in HelmRelease values)
- k3s uses its own CNI bin directory

## Dependencies

None - Multus can be installed independently of other components.

## Follow-on Tasks

After Multus is working:
1. Reserve a static IP for Home Assistant on the IoT network in UniFi
2. Update `20260103-home-assistant.md` to add the IoT network annotation to the HelmRelease
3. Deploy Home Assistant with IoT network access
