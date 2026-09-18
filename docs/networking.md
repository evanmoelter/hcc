# Networking

The address plan for the house and the cluster. This is the reference; [plans/20260816-talos-migration.md](../plans/20260816-talos-migration.md) describes the work that gets us there.

## VLANs

The UCG Fiber routes all three. Each `/22` follows `192.168.(4 × (ID - 1)).0/22`.

The device VLANs put DHCP in the lower half and statics in the upper half. HCC does not: its addressing is allocated per `/24`, so DHCP is confined to the shared block and every cluster block is static. Read each VLAN's DHCP range from the table rather than inferring it.

| ID | Name | Subnet | Gateway | DHCP | Purpose |
|---|---|---|---|---|---|
| 1 | Default | `192.168.0.0/22` | `192.168.0.1` | `192.168.0.10`–`192.168.1.254` | trusted devices |
| 2 | Home Automation | `192.168.4.0/22` | `192.168.4.1` | `192.168.4.10`–`192.168.5.254` | IoT devices |
| 6 | HCC | `192.168.20.0/22` | `192.168.20.1` | `192.168.20.100`–`192.168.20.254` | cluster compute |

IDs 4 and 5 are free for future non-cluster networks such as guest or cameras. ID 3 is not: its subnet under the formula, `192.168.8.0/22`, overlaps UniFi Teleport's client range at `192.168.8.0/24`, and a `/22` cannot start anywhere else in that space. Check Settings > VPN before claiming any ID; site-to-site and WireGuard server ranges reserve subnets the same way.

The old k3s cluster sits on VLAN 2 alongside the IoT devices. Apollo moves to VLAN 6, so cluster workloads no longer share a broadcast domain with every smart plug in the house.

## HCC VLAN

The `/22` divides into four `/24`s: one shared, three for clusters.

| Block | Use |
|---|---|
| `192.168.20.0/24` | DHCP, plus static non-cluster hosts at `.2`–`.99` |
| `192.168.21.0/24` | Apollo |
| `192.168.22.0/24` | free |
| `192.168.23.0/24` | free |

A new cluster claims a free `/24`; the old one's block returns to the pool when it is torn down. Three slots are enough because only two clusters ever run at once, during a migration.

Every cluster uses the same layout inside its `/24`, so the next migration is this document with one octet changed:

| Range | Use |
|---|---|
| `.1` | control-plane VIP |
| `.2` | free |
| `.3`–`.89` | nodes, `hccN` → `.N` |
| `.90`–`.99` | spare cluster-wide addresses |
| `.100`–`.199` | load-balancer IPs, assigned by hand from `.100` up |
| `.200`–`.254` | load-balancer headroom |

Two rules make the node mapping work:

- The names `hcc`, `hcc1`, and `hcc2` are retired, which frees `.1` for the VIP. Nothing is lost: the first Odroid is named `hcc` with no number, and both it and `hcc2` are disposed of in Wave 2.
- The `.200`+ headroom is a convention, not an enforced boundary. Cilium's LB-IPAM assigns from the low end of a pool, so an unpinned Service would take `.100`, not `.200`. Enforcing the split needs a second `CiliumLoadBalancerIPPool` with a `serviceSelector`, which is not worth building until a Service actually wants an automatic address.

## Apollo

| Host | IP | Role | Wave |
|---|---|---|---|
| — | `192.168.21.1` | control-plane VIP, Talos-native | 1 |
| hcc3 | `192.168.21.3` | worker | 2 |
| hcc4 | `192.168.21.4` | worker | 2 |
| hcc5 | `192.168.21.5` | control-plane | 1 |
| hcc6 | `192.168.21.6` | control-plane | 1 |
| hcc7 | `192.168.21.7` | control-plane | 1 |
| hcc8 | `192.168.21.8` | worker | 1 |

Nodes carry their address twice, and both records must be edited together:

- A UniFi Fixed IP, so a node in Talos maintenance mode boots straight onto its final address and `topf apply` has a known target. The node block sits outside the DHCP range, which UniFi permits; the reservation is for predictability, not conflict avoidance.
- A static address in the `topf` node patch, so the running cluster does not depend on the UCG's DHCP. Leases are 24 hours, and a control plane should not lose its addressing to a router outage.

| Service | IP |
|---|---|
| internal Gateway | `192.168.21.100` |
| external Gateway | `192.168.21.101` |
| paperless-sftp | `192.168.21.102` |

Declare the pool as an explicit `start`/`stop` range rather than a CIDR. `192.168.21.100`–`192.168.21.254` is not expressible as one CIDR, and Cilium reserves the first and last address of a CIDR block.

## Cluster-internal CIDRs

Distinct per cluster, so an address in a log names its cluster unambiguously while both exist.

| Cluster | Pods | Services |
|---|---|---|
| main | `10.69.0.0/16` | `10.96.0.0/16` |
| Apollo | `10.42.0.0/16` | `10.43.0.0/16` |

Home Assistant's `HASS_HTTP_TRUSTED_PROXY_2` currently names `10.96.0.0/12` and needs Apollo's value when it moves.

## Firewall

The HCC VLAN gets its own zone. Baseline: Default reaches HCC; HCC and Home Automation are isolated in both directions; HCC reaches the internet.

| Rule | Purpose |
|---|---|
| HCC → `192.168.4.1:443` | UniFi Integration API, for external-dns |
| HCC → `192.168.6.21:5432` | temporary; the old cluster's Postgres, for the authentik, Paperless, and TeslaMate imports. Remove once all three have moved. |

Home Assistant needs no rule. Its IoT interface is an attachment on VLAN 2 rather than traffic crossing the boundary, which is the point of doing it with multus.

## Home Assistant and the IoT VLAN

Home Assistant and its Matter Server need local IPv6 connectivity and multicast discovery on the IoT network.
The chosen Apollo design keeps their pod on VLAN 2 through a Multus macvlan attachment while its primary
interface remains on the cluster network. An Apple TV routes between Thread and VLAN 2; it does not provide
the pod's path from the cluster network to VLAN 2. An mDNS reflector alone would not provide that IPv6 path.
[Home Assistant's Matter guidance](https://www.home-assistant.io/integrations/matter/#general-recommendations)
recommends keeping the server and Thread border routers on the same LAN; IPv6 internet access is not required.

The Apollo scheduling design requires a verified IoT attachment and prefers hcc6; USB hardware is optional.
hcc5 and hcc7 are the initial additional candidates, with workers eligible after the same network verification.
Each eligible node needs VLAN 6 untagged and VLAN 2 tagged on its switch port, a Talos `bond0.2` link, and the
Multus CNI prerequisites. The shared NetworkAttachmentDefinition uses `bond0.2` as its macvlan parent, so
physical NIC names can differ between nodes. Only verified nodes receive the IoT capability label used by
HA's required node affinity; hcc6 uses preferred affinity. Node-specific Talos VLAN patches cover hcc5,
hcc6, and hcc7. Applying those patches and verifying the switch trunks are deployment prerequisites;
no node is marked eligible merely because its patch exists.

The attachment takes `192.168.6.100/22`: the upper half of VLAN 2, outside the DHCP range, with the `/22`
mask the subnet actually uses. It follows the single HA/Matter Server pod between eligible nodes. The current
cluster uses `192.168.4.100/24`, which sits inside the DHCP range with no reservation and carries the wrong mask.
Other workloads needing IoT discovery require their own attachment and address and the same node eligibility.

A Thread-capable Apple TV on VLAN 2 supplies the initial Thread border router and Apple home hub. Pair the
planned Aqara U400 directly with Apple Home for Home Key, then share it with HA through Matter. A future USB
radio runs with OTBR in a separate workload pinned to its hardware node, with its own IoT address and the
same Thread network credentials. It is not an HA sidecar or startup dependency; HA and Matter Server need
no USB mounts. This keeps HA movable even when the optional radio or its host is unavailable.

## Multus

Apollo runs the thin Multus plugin through the
[home-operations chart](https://github.com/home-operations/helm-charts/tree/main/charts/multus), following
[onedr0p's deployment](https://github.com/onedr0p/home-ops/tree/main/kubernetes/apps/kube-system/multus).
The chart installs the NetworkAttachmentDefinition CRD and the reference CNI binaries, including macvlan
and static IPAM. It uses Talos's `/etc/cni/net.d` and `/opt/cni/bin` paths. Multus needs root to install
host files; its main container uses `NET_ADMIN`, a read-only root filesystem, and no privilege escalation.
The installer init container inherits root and `RuntimeDefault` seccomp from the pod; the chart sets no
container-level security context, so its root filesystem is writable and privilege escalation is not disabled.
Cilium must retain `cni.exclusive: false` so it does not rename Multus's configuration out of the CNI search path.
Cilium manages `bond0`; `bpf.vlanBypass: [2]` allows the IoT VLAN through its parent-device filter.
Create the Talos VLAN links before rolling out this Cilium setting: Cilium discovers VLAN links at startup.
If a link is added afterward and packets still hit the VLAN filter, an operator-approved Cilium restart
may be needed. See [Cilium's VLAN guidance](https://docs.cilium.io/en/latest/configuration/vlan-802.1q/)
and the [Talos/macvlan report](https://github.com/cilium/cilium/issues/45719).

The `multus` Flux Kustomization waits for Cilium; `multus-config` waits for Multus and owns the shared
`kube-system/iot` attachment. The attachment adds a connected VLAN 2 route and leaves the primary Cilium
default route in place. The IoT address is intended for communication within VLAN 2; access HA from other
VLANs through its normal hostname, since this attachment does not configure a symmetric return path for
off-subnet clients. It does not allocate addresses or prevent duplicates. Consumers supply a unique
static address through their pod annotation. The planned HA/Matter pod uses:

```yaml
k8s.v1.cni.cncf.io/networks: >-
  [{"name":"iot","namespace":"kube-system","interface":"net1","ips":["192.168.6.100/22"]}]
```

The HA rebuild must depend on `multus-config`, use a single pod with a recreate update strategy, and require
`network.home.arpa/iot: "true"` through node affinity. Multus runs on every node, but only verified nodes
may host IoT consumers. Add that capability label through each verified node's Talos
`machine.nodeLabels`; leave it absent until the checks below pass. Static IPAM supplies IPv4 here;
local IPv6, Thread routing, and multicast must be verified separately before migrating Matter Server.
Cilium policy on the primary interface does not establish isolation for the direct IoT attachment.

### Deployment verification

Installation and IoT path verification are separate gates. On 2026-09-17, the operator confirmed all three
candidate nodes use the UniFi profile with HCC (6) native and Home Automation (2) tagged and applied the Talos
configuration. Read-only checks confirmed `bond0.2` up with VLAN ID 2 on hcc5, hcc6, and hcc7, all three nodes
Ready, healthy etcd and kubelet services, and all Longhorn disks Ready and Schedulable. Live Multus installation
and per-node IoT traffic verification remain pending.

1. Confirm each candidate node's UniFi port carries VLAN 6 untagged and VLAN 2 tagged. With operator
   approval, apply the committed Talos configuration one node at a time using
   `task talos:apply CLUSTER=apollo node=hcc5` (then hcc6 and hcc7). Confirm `bond0.2` exists with VLAN ID 2
   and parent `bond0`. The link intentionally has no host IPv4 address or default route.
   For standalone Talos checks, first run `task talos:talosconfig CLUSTER=apollo`, then inspect each node:

   ```sh
   talosctl --talosconfig kubernetes/apollo/bootstrap/talos/talosconfig --context apollo \
     --endpoints 192.168.21.5 --nodes 192.168.21.5 get links bond0.2 -o yaml
   ```

2. Merge after the VLAN links exist. Let Flux roll out Cilium's VLAN bypass, then install Multus through
   its dependency. Check installation without changing cluster state:

   ```sh
   kubectl --context apollo -n flux-system get kustomizations multus multus-config
   kubectl --context apollo -n kube-system get helmrelease multus
   kubectl --context apollo -n kube-system get daemonset multus
   kubectl --context apollo -n kube-system get pods -l app.kubernetes.io/name=multus -o wide
   kubectl --context apollo -n kube-system get network-attachment-definition iot
   ```

3. Before labeling a node, use an operator-approved, git-managed disposable pod pinned to it. Test one
   node at a time with an unused static address; `192.168.6.100/22` is reserved for HA and can serve as
   the test address only while no HA/Matter or other test pod owns it. Confirm the primary Cilium
   interface and default route still work, `net1` has the intended IPv4 and local IPv6 addresses,
   `192.168.4.1` is reachable through `net1`, and mDNS reaches the IoT network. Verify Thread routes
   and Matter discovery with the Apple TV on VLAN 2; an IPv4 ping alone does not satisfy this gate.
4. Remove the test workload through git and confirm it has terminated before reusing its address.
   Record the verified nodes and add their capability labels through Talos configuration with approval.
   HA migration requires hcc6 and at least one alternative node to pass.

Do not remove Multus while consumers still request secondary networks. Retire consumers first, then
remove the attachment and release through git; the chart cleans up its generated CNI configuration on exit.
