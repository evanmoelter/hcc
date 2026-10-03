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
- [ ] Review and pass CI on the independent test PR.
- [ ] With operator approval, merge the test PR and let Flux deploy the Jobs. Do not merge #325 yet.

Inspect results without changing the cluster:

```sh
kubectl --context apollo -n flux-system get kustomization iot-network-test
kubectl --context apollo -n default get jobs,pods -l app.kubernetes.io/name=iot-network-test -o wide
kubectl --context apollo -n default logs job/iot-network-test-hcc5-v1
kubectl --context apollo -n default logs job/iot-network-test-hcc6-v1
kubectl --context apollo -n default logs job/iot-network-test-hcc7-v1
```

Every Job must complete successfully with eight PASS results and a final PASS. A TCP-only success does
not establish Lutron authentication or device control. A gateway ping does not establish mDNS. The
mDNS check binds to the test address and requires `_lutron._tcp.local.` or `_hap._tcp.local.` to resolve
to the specified bridge; unrelated multicast responses do not pass. No service names or TXT properties
are printed. Each Job has a five-minute deadline, zero retries, and retains its result until cleanup.

| Node | Address | IPv4/routes/gateway | Lutron TCP/mDNS | Cluster/outbound | Result |
|---|---|---|---|---|---|
| hcc5 | `192.168.6.105/22` | pending | pending | pending | pending |
| hcc6 | `192.168.6.106/22` | pending | pending | pending | pending |
| hcc7 | `192.168.6.107/22` | pending | pending | pending | pending |

If a Job fails, inspect its named check failures and pod events. Review VLAN 2 trunks, `bond0.2`, Multus,
and Cilium VLAN bypass if IoT routing fails. Review multicast delivery if TCP passes but mDNS fails.
Do not label a node based on partial success. Retry through a new git revision with a new Job name
(e.g. `v2`), waiting for the previous pod on that node to terminate before its replacement uses the same
address. Changing scripts changes the generated ConfigMap reference and also requires new Job names.
Do not add a Job TTL: Flux would recreate the deleted Job and repeat the probe.

## Cleanup and eligibility

After recording results, remove the `iot-network-test` registration and app directory through git and
verify all three pods have terminated. Remove its temporary section from `docs/networking.md`, preserving
useful findings there, and archive this full execution record under `plans/done/`.

Prepare a separate Talos configuration change granting `network.home.arpa/iot-ipv4: "true"` only to nodes
that passed, and apply it with explicit operator approval. Verify the live labels before the HA outage.
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
