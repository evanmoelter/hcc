# Apollo gateway

Envoy Gateway provides Apollo's HTTP and HTTPS ingress in `network`. Household apps still run on
`main`. Cloudflare and UniFi external-dns provide split-horizon records, and Apollo has its own locally
managed Cloudflare tunnel. [DNS and tunnel integration](./dns.md) covers credentials and verification.

| Gateway | LoadBalancer IP | Purpose |
|---|---|---|
| `envoy-internal` | `192.168.21.100` | LAN ingress |
| `envoy-external` | `192.168.21.101` | Tunnel origin, also reachable from the LAN |

These addresses follow [networking.md](./networking.md). Both Gateways use the `envoy` GatewayClass and
EnvoyProxy, with two proxy replicas per Gateway. Cilium receives each pinned address through
`Gateway.spec.infrastructure.annotations`. The controller deploys proxies in the Gateway namespace.

Workloads run as UID/GID 568 with dropped capabilities and no privilege escalation. The proxy and its
shutdown sidecar allow filesystem writes: Envoy Gateway applies one container security configuration to both,
and the [shutdown manager](https://github.com/envoyproxy/gateway/blob/v1.9.1/internal/cmd/envoy/shutdown_manager.go)
writes `/tmp/shutdown-ready` without a writable volume mount. The controller and echo-server retain
read-only root filesystems. Controller, proxy, and echo metrics are scraped by Prometheus.

The proxy Services use `externalTrafficPolicy: Cluster` with Apollo's existing Cilium DSR mode to preserve
LAN source addresses. Cilium's [L2 announcements](https://docs.cilium.io/en/stable/network/l2-announcements/#limitations)
are incompatible with `Local`: the announcing node can lack a ready proxy endpoint.
[DSR](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/#direct-server-return-dsr)
preserves the source address when a different node serves the request.

A shared ClientTrafficPolicy requires TLS 1.2 or newer. Neither Gateway trusts X-Forwarded-For hops or
CIDRs. Tunnel forwarding and app proxy trust remain work in
[the ingress plan](../plans/04-envoy-gateway.md).

HTTP listeners accept routes from `network`; one shared route redirects requests to HTTPS. HTTPS
listeners accept application HTTPRoutes from any namespace. Both reference the production `wildcard`
TLS Secret in `network`, so no cross-namespace certificate grant is needed.
[certificates.md](./certificates.md) describes issuance.

Controller installation, certificates, and gateway configuration reconcile separately. The certificates
Kustomization waits for `cert-manager-issuers`; configuration waits for the controller and certificate.
The `echo-server` test route attaches `echo-apollo.${SECRET_DOMAIN}` to the external HTTPS listener for
split-horizon testing. Public DNS sends it through the tunnel; UniFi sends it directly to the external
Gateway's LAN address. After testing, move its parent to `envoy-internal` to remove public access.

## LAN verification

On 2026-09-11, the production wildcard was Ready, both Gateways were Accepted and Programmed with two
ready replicas each, and echo-server was Accepted with ResolvedRefs on both parents. Both addresses
returned HTTP 301 and successful HTTPS with certificate verification. `x-envoy-external-address` preserved
the workstation's source address even with a forged X-Forwarded-For header. The LAN gate passed.

The commands below repeat that baseline check with echo attached to both HTTPS listeners. During
split-horizon testing it attaches only to `envoy-external`, so use only `192.168.21.101` for echo requests.
They inspect status without reading Secret contents:

```sh
flux --context apollo get kustomizations -A
kubectl --context apollo -n network get helmrelease,certificate,gateway,httproute
kubectl --context apollo -n network get deployment,pod,service -o wide
kubectl --context apollo -n network describe gateway envoy-internal envoy-external
kubectl --context apollo -n network describe httproute echo-server
```

Confirm the certificate is Ready, both Gateways are Accepted and Programmed at their assigned addresses,
and echo-server's route is Accepted with ResolvedRefs on both parents. Each Gateway should have two ready
proxy replicas. Check that the generated Services have `externalTrafficPolicy: Cluster`:

```sh
kubectl --context apollo -n network get service -o custom-columns=NAME:.metadata.name,IP:.status.loadBalancer.ingress,TRAFFIC:.spec.externalTrafficPolicy
```

From a LAN workstation that can reach the HCC VLAN, set `gateway_test_host` to the actual echo hostname.
Do not retrieve the domain from Secret resources. These requests bypass DNS while retaining the correct
Host header and TLS SNI; use a direct connection without a configured HTTP proxy:

```sh
gateway_test_host='echo-apollo.YOUR_DOMAIN'
for gateway_test_ip in 192.168.21.100 192.168.21.101; do
  curl --noproxy '*' --resolve "${gateway_test_host}:80:${gateway_test_ip}" \
    --silent --show-error --dump-header - --output /dev/null "http://${gateway_test_host}/"
  curl --noproxy '*' --resolve "${gateway_test_host}:443:${gateway_test_ip}" \
    --fail --silent --show-error "https://${gateway_test_host}/"
  curl --noproxy '*' --resolve "${gateway_test_host}:443:${gateway_test_ip}" \
    --fail --silent --show-error -H 'X-Forwarded-For: 198.51.100.123' \
    "https://${gateway_test_host}/"
done
```

Expect an HTTP 301 with the same hostname and HTTPS scheme, then successful HTTPS responses without
`--insecure`. That verifies the certificate chain and hostname as well as routing. In both echo responses,
`x-envoy-external-address` must match the workstation's source address, never the forged `198.51.100.123`
or a cluster node address. X-Forwarded-For may retain the untrusted supplied value as part of a chain;
its mere presence does not demonstrate trust. Do not configure app trusted proxies until this test passes.
Record the results before proceeding to DNS and tunnel integration.

## References

The shared EnvoyProxy/GatewayClass and separate Gateways draw from
[onedr0p](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/network/envoy-gateway/app/envoy.yaml),
[billimek](https://github.com/billimek/k8s-gitops/tree/master/kubernetes/kube-system/envoy-gateway),
[szinn](https://github.com/szinn/k8s-homelab/tree/main/kubernetes/main/apps/network/envoy-gateway),
[Mafyuh](https://github.com/Mafyuh/iac/blob/main/kubernetes/cluster/envoy-gateway/config/envoy.yaml), and
[joryirving](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/network/envoy-gateway/config/envoy.yaml).
Their traffic policies depend on their network topology; Apollo's Cilium settings determine its Service policy.
Envoy Gateway documents [proxy customization](https://gateway.envoyproxy.io/docs/tasks/operations/customize-envoyproxy/)
and the [ClientTrafficPolicy API](https://gateway.envoyproxy.io/docs/api/extension_types/#clienttrafficpolicy).
