# Apollo Tailscale

Apollo has its own Tailscale operator hostname, OAuth client, and tags. The operator handles
`tailscale` Ingresses; `echo-apollo` is the first endpoint. Kubernetes API access, subnet routes,
and Funnel are disabled. Household app names remain owned by `main` until each app's cutover.

## Operator setup

Before deployment, merge these tag owners into the existing tailnet policy:

```json
{
  "tagOwners": {
    "tag:apollo-operator": ["autogroup:admin"],
    "tag:apollo": ["tag:apollo-operator"]
  }
}
```

Tag ownership lets the operator register devices; it does not grant users access. Add a grant for
the intended test users or groups to `tag:apollo` on `tcp:443`. Review existing broad grants as well:
separate tags do not override an existing allow rule. Keep the old cluster's tags and OAuth client
through Wave 1.

Create a new OAuth client for Apollo in Tailscale's Trust credentials page. Following the
[operator installation guide](https://tailscale.com/docs/kubernetes-operator/install-operator), give it
write scopes for **General / Services**, **Devices / Core**, and **Keys / Auth Keys**, scoped to
`tag:apollo-operator`. Enable MagicDNS and HTTPS certificates in the tailnet if they are not already enabled.

Create this item in the `hcc-apollo` 1Password vault:

| Item | Field | Value |
|---|---|---|
| `tailscale-operator` | `client_id` | New OAuth client ID |
| `tailscale-operator` | `client_secret` | New OAuth client secret |

ESO creates `network/operator-oauth`, which the chart mounts directly. Credentials are not Helm values.
The operator opts into Reloader for credential rotation. Its device identity is stored separately in
the operator-managed `network/operator` Secret; preserve that state during routine updates.

## Reconciliation and security

Flux orders `onepassword-store` → `tailscale-operator` → `tailscale-config` → `echo-server-tailscale`.
The echo satellite also waits for `echo-server`, keeping tailnet setup independent of its Gateway route.
The config Kustomization waits for `ProxyClassReady`; the echo satellite waits for an Ingress hostname.
An assigned hostname still needs an end-to-end HTTPS check.

The operator and Ingress proxy run as UID/GID 568 with dropped capabilities and no privilege escalation.
They fit the existing restricted `network` namespace. The operator has a read-only root filesystem and
a small `/tmp` emptyDir for tsnet's configuration and logs. Its Helm post-renderer adds that volume and
the Deployment's Reloader annotation; the pinned chart does not render the documented
`operatorConfig.annotations` value onto the Deployment.

The `tailscale-ingress` ProxyClass is selected explicitly on each Ingress. Standalone HTTPS Ingresses
use Tailscale's userspace proxy. Its filesystem remains writable for the socket and runtime files in
`/tmp`: the pinned ProxyClass API cannot add an emptyDir or volume mount. Persistent device state lives
in operator-managed Kubernetes Secrets, so no Longhorn volume is needed.

This class is for standalone HTTPS Ingresses only. Adding Service exposure, subnet routing, or HA
ProxyGroups needs a separate security review. Tailscale's
[Cilium compatibility requirements](https://tailscale.com/docs/kubernetes-operator/reference/compatibility)
require socket-load-balancer bypass for Service and Service-CIDR exposure; this userspace Ingress does
not require that Cilium change.

## Verify after deployment

Deployment and tailnet verification remain pending. After the credentials and policy are ready and
Flux has applied the manifests:

```sh
flux --context apollo get kustomizations -A
flux --context apollo get helmreleases -n network
kubectl --context apollo -n network get externalsecret tailscale-operator
kubectl --context apollo get proxyclass tailscale-ingress
kubectl --context apollo -n network get ingress echo-server-tailscale
```

Confirm `tailscale-operator-apollo` appears online with `tag:apollo-operator`, and `echo-apollo` with
`tag:apollo`, in Tailscale's Machines page. From an authorized tailnet client, request
`https://echo-apollo.<tailnet>.ts.net/`, using the full hostname reported by the Ingress. Verify a trusted
certificate and an echo response from Apollo. A client without the access grant should fail to connect.
Keep the existing Gateway tests separate; this Ingress reaches echo's ClusterIP directly and uses
Tailscale-managed TLS, not Envoy or cert-manager.

For later app migrations, add a `ks-tailscale.yaml` satellite depending on the app and `tailscale-config`,
select `tailscale-ingress`, and retain the old short hostname only after `main` releases it. Never let
both clusters claim an app name during cutover.

## References

The direct OAuth Secret pattern follows
[billimek's operator](https://github.com/billimek/k8s-gitops/tree/master/kubernetes/kube-system/tailscale).
Apollo uses Tailscale's upstream stable Helm repository, as it does for Longhorn, and retains standalone
[Ingress resources](https://tailscale.com/docs/kubernetes-operator/ingress) from the migration plan.
The other requested community repositories had no comparable Kubernetes operator configuration when reviewed.
