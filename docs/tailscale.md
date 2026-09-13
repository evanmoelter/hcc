# Apollo Tailscale

## Before merging

Create a dedicated Apollo OAuth client following [Tailscale's setup guide](https://tailscale.com/docs/kubernetes-operator/install-operator).
Give it write scopes for **Services**, **Devices / Core**, and **Auth Keys**, scoped to `tag:apollo-operator`.
Store `client_id` and `client_secret` in the `tailscale-operator` item in the `hcc-apollo` 1Password vault.
Enable MagicDNS and HTTPS certificates. Missing credentials or tag ownership stall reconciliation.

Merge these entries into the tailnet's `tagOwners`:

```json
"tag:apollo-operator": [],
"tag:apollo": ["tag:apollo-operator"]
```

The current allow-all ACL already permits HTTPS access; a separate grant would not restrict it.
Keep the old operator's credentials through Wave 1, and release each app hostname on `main` before Apollo claims it.

## Operational notes

- Preserve the operator-managed device-state Secrets during updates; OAuth credentials are separate.
- The Helm post-renderer supplies writable `/tmp` for tsnet's configuration and logs because the chart cannot add volumes.
  It also adds the Reloader annotation; the chart ignores its documented `operatorConfig.annotations` value.
- The Ingress proxy needs writable `/tmp` for runtime files. Its root remains writable because ProxyClass cannot add volumes.
  This class supports standalone HTTPS Ingresses only; Service exposure and subnet routing also need
  [Cilium compatibility changes](https://tailscale.com/docs/kubernetes-operator/reference/compatibility).
- The chart uses the signed [community OCI mirror](https://github.com/home-operations/charts-mirror).
  Switch to upstream OCI when available; the mirror prunes charts six months after upstream support arrives.

## Verification

Deployment, HTTPS access, and credential rotation remain unverified. After Flux is ready, get echo's hostname with
`kubectl --context apollo -n network get ingress echo-server-tailscale` and request its HTTPS URL from a tailnet client.
Verify a trusted certificate and an Apollo echo response. An assigned Ingress hostname alone does not prove connectivity.
