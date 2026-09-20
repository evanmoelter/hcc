# Apollo gateway

Envoy Gateway provides Apollo's HTTP and HTTPS ingress in `network`. Mealie uses LAN/public routes
on Apollo; other household apps remain on `main`. Cloudflare and UniFi external-dns provide split-horizon records, and Apollo has its own locally
managed Cloudflare tunnel. [DNS and tunnel integration](./dns.md) covers credentials and verification.

Mealie uses the same canonical hostname on both paths and authenticates through Authentik on `main`.
Its separate Tailscale Ingress was removed because login redirected to the canonical hostname.

| Gateway | LoadBalancer IP | Purpose |
|---|---|---|
| `envoy-internal` | `192.168.21.100` | LAN ingress |
| `envoy-external` | `192.168.21.101` | Tunnel origin; HTTPS restricted to cloudflared |

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

Each Gateway has its own ClientTrafficPolicy. A shared Kustomize patch supplies the TLS 1.2 minimum
to both, so common settings have one definition without relying on policy merging. The external Gateway
detects client addresses from X-Forwarded-For using Apollo's pod CIDR as its trusted proxy range.
The internal Gateway does not trust forwarded headers. External X-Forwarded-For client detection passed
the [origin verification](#client-ip-verification). App proxy-header checks remain work in
[the ingress plan](../plans/04-envoy-gateway.md).

The external Gateway's ingress NetworkPolicy admits only cloudflared pods in `network` to its HTTPS
listener, and the bootstrap Prometheus in `monitoring` to its metrics port. It selects the generated proxy
pods by their owning-Gateway labels. Envoy Gateway adds 10000 to listener ports below 1024 for the
unprivileged proxy: HTTPS 443 maps to target port `10443`. Metrics uses `19001` separately.
Cloudflared's origin uses HTTPS, so the policy does not allow HTTP target port `10080`.
When adding or changing listeners, check the generated Service target ports and update the policy for
the intended callers. Egress stays unrestricted for xDS, DNS, and backend connections.
The internal Gateway remains the direct LAN path. Keeping the external LoadBalancer address does not
grant LAN access through the policy.

This restriction is the prerequisite for trusting cloudflared's forwarded headers. Its replicas use Apollo's
shared pod CIDR, so trusting that range without the policy would also trust unrelated pods. The isolation
gate passed on 2026-09-17 before external-only CIDR trust was configured. NetworkPolicy application
is asynchronous; Flux readiness alone does not prove enforcement. Existing connections may survive a policy
change, so verification must use new connections and account for any previously open connections.
Policies are additive: another policy allowing these listener ports would widen the boundary.
Local-node traffic remains allowed for kubelet probes; privileged node access and permission to create or
relabel cloudflared pods remain trusted administrative capabilities.

HTTP listeners accept routes from `network`; one shared route redirects requests to HTTPS. HTTPS
listeners accept application HTTPRoutes from any namespace. Both reference the production `wildcard`
TLS Secret in `network`, so no cross-namespace certificate grant is needed.
[certificates.md](./certificates.md) describes issuance.

Controller installation, certificates, and gateway configuration reconcile separately. The certificates
Kustomization waits for `cert-manager-issuers`; configuration waits for the controller and certificate.
Echo uses two routes for `echo-apollo.${SECRET_DOMAIN}`: the chart's `echo-server` route attaches to the
external HTTPS listener, and `echo-server-internal` attaches to the internal HTTPS listener. Both send
traffic to the same Service. The echo chart exposes one route, so the additional route is a separate manifest.
Public DNS sends requests through the tunnel; UniFi sends LAN requests to the internal Gateway.
Echo remains publicly accessible throughout the cluster migration so it is available for further testing.
After the migration is complete, disable the chart's `httpRoute.enabled` value to remove public access while
retaining the internal route. The [migration design](../plans/20260816-talos-migration.md#dns-and-ingress) records
dual routes as a soft decision, revisitable if their maintenance becomes burdensome.

## LAN verification

On 2026-09-11, the production wildcard was Ready, both Gateways were Accepted and Programmed with two
ready replicas each, and echo-server was Accepted with ResolvedRefs on both parents. Both addresses
returned HTTP 301 and successful HTTPS with certificate verification. `x-envoy-external-address` preserved
the workstation's source address even with a forged X-Forwarded-For header. The LAN gate passed.

On 2026-09-17 UTC, Flux applied the dual-route configuration at revision `f7e1f5c`. Both echo routes were
Accepted with ResolvedRefs at their current generations. Both Gateway-specific client policies were Accepted,
and the former shared policy was absent. Both Gateways returned HTTP 301 redirects and HTTPS 200 echo
responses with certificate verification. Forged X-Forwarded-For and CF-Connecting-IP headers did not change
`x-envoy-external-address` from the LAN workstation's address on either Gateway.

Those checks predate the tunnel-only policy. After deployment, direct external-Gateway requests must fail.
Inspect status without reading Secret contents:

```sh
flux --context apollo get kustomizations -A
kubectl --context apollo -n network get helmrelease,certificate,gateway,httproute
kubectl --context apollo -n network get deployment,pod,service -o wide
kubectl --context apollo -n network describe gateway envoy-internal envoy-external
kubectl --context apollo -n network describe httproute echo-server echo-server-internal
kubectl --context apollo -n network get clienttrafficpolicy
kubectl --context apollo -n network describe networkpolicy envoy-external
```

Confirm the certificate is Ready, both Gateways are Accepted and Programmed at their assigned addresses,
and both echo routes are Accepted with ResolvedRefs on their respective parents. Each ClientTrafficPolicy
must be Accepted for its own Gateway, with no conflict or override; the former shared `envoy` policy must
be absent. Each Gateway should have two ready proxy replicas. Check that the generated Services have
`externalTrafficPolicy: Cluster`:

```sh
kubectl --context apollo -n network get service -o custom-columns=NAME:.metadata.name,IP:.status.loadBalancer.ingress,TRAFFIC:.spec.externalTrafficPolicy
```

From a LAN workstation that can reach the HCC VLAN, set `gateway_test_host` to the actual echo hostname.
Do not retrieve the domain from Secret resources. These requests bypass DNS while retaining the correct
Host header and TLS SNI; use a direct connection without a configured HTTP proxy:

```sh
gateway_test_host='echo-apollo.YOUR_DOMAIN'
gateway_test_ip=192.168.21.100
curl --noproxy '*' --resolve "${gateway_test_host}:80:${gateway_test_ip}" \
  --silent --show-error --dump-header - --output /dev/null "http://${gateway_test_host}/"
curl --noproxy '*' --resolve "${gateway_test_host}:443:${gateway_test_ip}" \
  --fail --silent --show-error "https://${gateway_test_host}/"
curl --noproxy '*' --resolve "${gateway_test_host}:443:${gateway_test_ip}" \
  --fail --silent --show-error -H 'X-Forwarded-For: 198.51.100.123' \
  -H 'CF-Connecting-IP: 198.51.100.124' \
  "https://${gateway_test_host}/"
```

Expect an HTTP 301 with the same hostname and HTTPS scheme, then successful HTTPS responses without
`--insecure`. That verifies the certificate chain and hostname as well as routing. In both echo responses,
`x-envoy-external-address` must match the workstation's source address, never the forged `198.51.100.123`
or a cluster node address. X-Forwarded-For may retain the untrusted supplied value as part of a chain;
its mere presence does not demonstrate trust. Do not configure app trusted proxies until this test passes.
Record the results before proceeding to DNS and tunnel integration.

## External isolation gate

On 2026-09-17, the deployed policy at revision `0034ea9` passed live enforcement checks:

- Fresh LAN connections to the external LoadBalancer timed out on both 80 and 443; internal HTTP redirected
  and internal HTTPS returned 200 with valid TLS.
- An ordinary pod in `network` and a pod carrying cloudflared labels in `monitoring` each reached internal
  HTTPS successfully. Both were denied on the external Service and LoadBalancer ports 80/443, and on each
  external proxy pod's ports 10080/10443. These requests included forged forwarding headers. All 18 checks
  passed, and both temporary pods were deleted afterward.
- Public-address HTTPS requests returned 200 and were correlated with origin access logs. Logs also confirmed
  successful requests from both cloudflared replicas after the policy took effect, reaching both external
  proxy replicas. Both tunnel replicas retained four connections and reported no request errors.
- Both external proxy metrics targets and both cloudflared targets stayed healthy. No other NetworkPolicy
  in `network`, CiliumNetworkPolicy, or CiliumClusterwideNetworkPolicy widened the listener allowance.
- The operator independently confirmed echo access from off-LAN.

Repeat the following checks after changes to the policy, proxy placement, or workload selectors:

- Confirm fresh direct LAN requests to `192.168.21.101` on both 80 and 443 fail, including forged-header
  requests. Rerun the LAN snippet with `gateway_test_ip=192.168.21.101` and add
  `--connect-timeout 5 --max-time 10` to every curl command. Cilium's `policy-deny-response: none` silently
  drops denied traffic, so expect a connection timeout rather than a refusal. Any HTTP response, including
  403 or 404, means the network isolation check failed. A timeout alone does not prove enforcement:
  confirm the positive tunnel and readiness checks below, and inspect Cilium policy drops if ambiguous.
- Verify a non-cloudflared pod cannot connect to either external listener through the Service or either
  proxy pod IP. Also check a pod with cloudflared labels in another namespace is denied. Creating temporary
  probe pods requires operator approval. Check both proxy replicas and use new connections.
- Verify both cloudflared replicas can still reach the origin and public HTTPS echo requests succeed with
  valid TLS. Use an independent off-LAN connection as well as the public-address test from the LAN.
- Confirm both external proxy replicas remain Ready and both Prometheus targets on port 19001 stay up.
  Recheck other policies for additive listener allowances before treating this gate as passed.

## Client-IP verification

On 2026-09-17, Flux applied revision `b43eb2d`. Both ClientTrafficPolicies were Accepted at their current
generations, with only the external policy containing `clientIPDetection`. Normal public requests and requests
with a forged X-Forwarded-For value returned HTTPS 200; correlated origin logs identified the client's public
address reported independently by Cloudflare's trace endpoint. Normal LAN requests and requests with forged
X-Forwarded-For, CF-Connecting-IP, or both identified the LAN client's address. Direct external-Gateway LAN
connections still timed out on 80/443, and all seven gateway and tunnel metrics targets stayed healthy.

Cloudflare rejected public requests carrying a forged CF-Connecting-IP header with HTTP 403 before they
reached the origin. External-origin handling of that header was not exercised. The configured
[Envoy XFF detector](https://github.com/envoyproxy/envoy/blob/v1.39.1/source/extensions/http/original_ip_detection/xff/xff.cc)
uses X-Forwarded-For, not CF-Connecting-IP; application proxy-header validation remains a separate requirement.

Verify normal and forged-header tunnel requests against Envoy's `downstream_remote_address` access-log
field. CIDR detection uses the original-IP extension and may omit `x-envoy-external-address`; that header
is not the external-path verification oracle. Detection does not sanitize every forwarded header, so app
proxy configuration still needs its own checks. A Cloudflare 403 without an origin request proves nothing
about Envoy's handling of that request.

Use a unique query parameter for each request and match it to `x-envoy-origin-path` in the default JSON
access logs. Compare the detected address with the client's independently known public address, and confirm
that a forged X-Forwarded-For value cannot replace it. Test CF-Connecting-IP separately and record whether
the request reached the origin; an edge rejection does not establish origin behavior. Repeat the
internal-Gateway forged-header check above; it must still identify the LAN client. Recheck isolation and
metrics health. Retain echo's external route for further testing throughout the migration. After the migration
is complete, move Gatus to a retained public endpoint and repeat the
[alert-delivery gate](./monitoring.md#deployment-and-alert-delivery-gate) before removing echo's external route
and completing the DNS cleanup in [dns.md](./dns.md).

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
The pod-CIDR trust mechanism follows onedr0p, szinn, and joryirving, with Apollo's external listener isolation
as a prerequisite. Kubernetes documents [NetworkPolicy enforcement and existing connections](https://kubernetes.io/docs/concepts/services-networking/network-policies/#pod-lifecycle);
Envoy documents [CIDR client detection](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/http/original_ip_detection/xff/v3/xff.proto)
and [forwarded-header behavior](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_conn_man/headers.html#x-forwarded-for).
The [Gateway translator](https://github.com/envoyproxy/gateway/blob/v1.9.1/internal/gatewayapi/translator.go)
defines the privileged-port offset; Cilium documents [policy deny responses](https://docs.cilium.io/en/stable/security/policy/intro/#policy-deny-response-handling).
