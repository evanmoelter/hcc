# Home Assistant

Home Assistant uses the LAN Gateway at `ha.${SECRET_DOMAIN}` and the `ha` Tailscale identity.
The configuration editor remains LAN-only at `ha-code.${SECRET_DOMAIN}` with authentication disabled,
matching the old deployment. Neither service has a public Gateway route. HA trusts Apollo's pod CIDR
through `${CLUSTER_CIDR}` because Envoy and Tailscale proxy connections originate from pods.

The config PVC contains integrations, automations, credentials, and local customizations. Git supplies
`configuration.yaml`; edit that file in the repository. PostgreSQL holds recorder history and uses the
[database recovery lifecycle](databases.md). Config backups use the separate Apollo restic repository
`tf-hcc-apollo-volsync/home-assistant-config`. Config and database backups were verified after cutover.
The bound config PVC retains its immutable restore reference after temporary restore resources are removed.
A replacement PVC requires an explicit new recovery setup; see the [VolSync lifecycle](../kubernetes/apollo/components/volsync/README.md#restore-lifecycle).

HA's application environment comes from the `home-assistant-app` item in `hcc-apollo`. ESO selects
fields whose labels are uppercase environment-variable names; keep only application credentials in
that item. Database credentials come from CNPG, and proxy trust and timezone stay in the manifest.
The configuration editor runs under the same UID as HA, with a writable home under `/config/.vscode`
and disposable cache and temporary directories.

## IoT access and deferred Matter

HA retains the Multus `net1` attachment at `192.168.6.100/22` for existing integrations such as Lutron
Caséta. It can schedule on any node labeled `network.home.arpa/iot-ipv4: "true"`, with no hostname
restriction or preference. hcc5, hcc6, and hcc7 have the required Multus setup and passed IPv4/mDNS probes.
Grant the label through Talos configuration when additional nodes have the same verified network setup. The separate `network.home.arpa/iot` label remains reserved for the future
IPv6/Thread verification gate. Neither label is assigned merely because Multus is installed.

Matter Server is omitted at the operator's request until a Thread-capable Apple TV is available.
The old controller reported zero paired nodes and HA's entity registry contained no Matter entities
when preparation began. Its old PVC is retained for rollback; Apollo creates no Matter PVC or USB mounts.

When enabling Matter, follow [the networking verification](networking.md#home-assistant-and-the-iot-vlan):
verify local IPv6, Router Advertisement route information, multicast discovery, and Thread reachability
inside the pod on hcc6 and an alternative node. Select compatible HA/Matter versions at that time; do not
assume the retained Python Matter image remains the right choice. Add persistent Matter state and its
backup, keep HA/Matter together with one replica and Recreate updates, and verify rescheduling preserves
pairings and device control. An optional future OTBR remains a separate workload.

Recreate prevents overlap during updates; it does not fence a failed node. Confirm the old instance has
stopped or fence its node before starting a replacement with the same static IoT address.

[The migration record](../plans/done/20261003-home-assistant-migration.md) tracks preparation, operator
prerequisites, verified cutover and backups, cleanup, and the operator's decision to omit a forced-node test.
