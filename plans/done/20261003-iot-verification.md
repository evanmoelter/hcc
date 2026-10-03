# Apollo IPv4 IoT verification

## Scope

One independent PR deploys three temporary Jobs concurrently, before the Home Assistant disable PR #325.
Existing HA remains on main. The operator confirmed that only `192.168.6.7` is occupied in that /24 and
identified the Lutron bridge as `192.168.4.35`; test addresses `.105`, `.106`, and `.107` are allocated to
hcc5, hcc6, and hcc7 respectively. All use `/22`, `net1`, and the existing `kube-system/iot` attachment.

No Matter/Thread, pairing, device commands, credential access, HA data mounts, or node-label changes occur.
The Jobs open and close TCP connections to the bridge without authenticating. Cluster API access checks
only the TCP connection, with no ServiceAccount token; outbound access checks a public HTTPS TLS handshake.

## Deployment and verification

- [x] Operator confirmed the three test addresses are unused and supplied the bridge address.
- [x] Review and pass CI on the independent test PR.
- [x] With operator approval, merge the test PR and let Flux deploy the Jobs. Do not merge #325 yet.

Inspect results without changing the cluster:

```sh
kubectl --context apollo -n flux-system get kustomization iot-network-test
kubectl --context apollo -n default get jobs,pods -l app.kubernetes.io/name=iot-network-test -o wide
kubectl --context apollo -n default logs job/iot-network-test-hcc5-v3
kubectl --context apollo -n default logs job/iot-network-test-hcc6-v3
kubectl --context apollo -n default logs job/iot-network-test-hcc7-v3
```

Every Job must complete successfully with eight PASS results and a final PASS. A TCP-only success does
not establish Lutron authentication or device control. A gateway ping does not establish mDNS. The
mDNS check binds to the test address and requires `_lutron._tcp.local.` or `_hap._tcp.local.` to resolve
to the specified bridge; unrelated multicast responses do not pass. No service names or TXT properties
are printed. Each Job has a five-minute deadline, zero retries, and retains its result until cleanup.

| Node | Address | IPv4/routes/gateway | Lutron TCP/mDNS | Cluster/outbound | Result |
|---|---|---|---|---|---|
| hcc5 | `192.168.6.105/22` | PASS | PASS | PASS | PASS |
| hcc6 | `192.168.6.106/22` | PASS | PASS | PASS | PASS |
| hcc7 | `192.168.6.107/22` | PASS | PASS | PASS | PASS |

If a Job fails, inspect its named check failures and pod events. Review VLAN 2 trunks, `bond0.2`, Multus,
and Cilium VLAN bypass if IoT routing fails. Review multicast delivery if TCP passes but mDNS fails.
Do not label a node based on partial success. Retry through a new git revision with a new Job name
(e.g. `v4`), waiting for the previous pod on that node to terminate before its replacement uses the same
address. Changing scripts changes the generated ConfigMap reference and also requires new Job names.
Do not add a Job TTL: Flux would recreate the deleted Job and repeat the probe.

## Execution record

The v1 Jobs from PR #331 reached Apollo on 2026-10-03 but Pod Security rejected every Pod because
`NET_RAW` is forbidden by the cluster's baseline policy. No test pod ran and no network gate passed.
The v2 Jobs drop all capabilities and use the allowed pod-local `net.ipv4.ping_group_range: "568 568"`
for unprivileged ICMP. Ping binds its source address, with `net1` routing checked separately.
The existing hardened HA container successfully ran a source-bound loopback ping without capabilities;
this verifies image support, not Apollo's IoT path. Fresh names avoid immutable Job-template updates.
All three corrected Pod templates passed server-side dry-run admission on Apollo; no pods were created
by that validation. Five unit/render tests and policy lint passed before deployment.

The v2 Jobs started successfully on all three nodes. Each passed source-bound gateway ICMP and Lutron
mDNS discovery, but the six other checks stopped at address/route inspection: the image provides BusyBox
`ip`, which rejects the `-j` option. Those failures do not establish that TCP or outbound connectivity is
broken; the connections were not attempted after route inspection failed. The v3 probe parses supported
BusyBox text output and preserves the same interface/source/prefix assertions. The corrected parser was
exercised in the pinned HA image against real address, default-route, and destination-route output. Cluster DNS/API TCP and outbound
DNS/TLS checks also passed there; this runtime check validates image compatibility, not Apollo eligibility.

PR #334 merged as `8f2d3ca2ee08c49f939b9f0ec490303d6b382584` on 2026-10-03. Flux reported the
`iot-network-test` Kustomization Ready at that revision. All three v3 Jobs completed successfully:
hcc5 and hcc6 in six seconds, hcc7 in seven seconds. Each log contained all eight named PASS results
and a final PASS with an empty `failed_checks` list. The checks were `iot_address`,
`primary_default_route`, `iot_gateway_route`, `iot_gateway_ping`, `lutron_tcp`,
`cluster_dns_and_api_tcp`, `outbound_dns_and_tls`, and `lutron_mdns`.

## Cleanup and eligibility

PR #335 removed the `iot-network-test` registration, app directory, and probe-specific tests. On
2026-10-03, read-only checks confirmed the Flux Kustomization, Jobs, Pods, and generated ConfigMap were
absent after Flux applied `c32f07729843eb2244e090eb248fba8a38705dec`. The test addresses `.105`, `.106`,
and `.107` are released. The result is preserved here and in `docs/networking.md`.

- [x] All three nodes passed every IPv4 probe check.
- [x] Merge cleanup and verify the temporary resources are gone.
- [x] Apply the separately reviewed Talos eligibility labels and verify them live.

PR #336 added `network.home.arpa/iot-ipv4: "true"` to hcc5, hcc6, and hcc7. With explicit operator
approval on 2026-10-03, the following commands applied it sequentially. Each Talos dry run showed only
the IPv4 label being added; each apply completed its stabilization check before proceeding:

```sh
task talos:apply CLUSTER=apollo node=hcc5 mode=no-reboot
task talos:apply CLUSTER=apollo node=hcc6 mode=no-reboot
task talos:apply CLUSTER=apollo node=hcc7 mode=no-reboot
kubectl --context apollo get nodes -L network.home.arpa/iot-ipv4,network.home.arpa/iot
```

Final read-only checks confirmed all three nodes Ready with the IPv4 label set to `true` and the full
`network.home.arpa/iot` label absent. All applies used `no-reboot`; no reboot was requested. The network
verification, cleanup, and IPv4 scheduling-label gates are complete.
HA requires hcc6 and at least one alternative; this test covers all three current nodes. No test labels a
node automatically. IPv6/Thread and the full `network.home.arpa/iot` capability stay deferred until Apple TV
and Matter are introduced. The HA address `.100`, callbacks, authentication, and actual device control
remain separate cutover checks.

## Upstream references

The [HA 2025.12.5 Lutron manifest](https://github.com/home-assistant/core/blob/2025.12.5/homeassistant/components/lutron_caseta/manifest.json)
uses Lutron discovery and HomeKit Smart Bridge discovery. Its pinned
[pylutron-caseta client](https://github.com/gurumitts/pylutron-caseta/blob/v0.26.0/src/pylutron_caseta/smartbridge.py)
connects over IPv4 TCP 8081. The probe uses the installed
[Zeroconf 0.148.0 API](https://github.com/python-zeroconf/python-zeroconf/blob/0.148.0/examples/browser.py)
with an explicit interface and `IPVersion.V4Only`.
