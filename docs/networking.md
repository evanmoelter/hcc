# Networking

The address plan for the house and the cluster. This is the reference; [plans/20260816-talos-migration.md](../plans/20260816-talos-migration.md) describes the work that gets us there.

## VLANs

The UCG Fiber routes all three. Each `/22` follows `192.168.(4 × (ID - 1)).0/22`, DHCP in the lower half, statics in the upper half.

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

Matter discovery is mDNS over IPv6, and with no IPv6 subnet configured it runs on link-local addresses. Those are scoped to a single L2 segment and cannot be routed or reflected between VLANs. A macvlan attachment onto VLAN 2 is therefore the only mechanism that works, not a convenience.

Home Assistant is pinned to hcc7, which needs VLAN 6 untagged and VLAN 2 tagged on its switch port. The attachment takes `192.168.6.100/22`: the upper half of VLAN 2, outside the DHCP range, with the `/22` mask the subnet actually uses. The current cluster uses `192.168.4.100/24`, which sits inside the DHCP range with no reservation and carries the wrong mask.

Any other workload needing IoT discovery needs its own attachment and the same node pinning.
