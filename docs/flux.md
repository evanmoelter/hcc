# Apollo Flux configuration

Apollo keeps child Flux Kustomizations in `flux-system`, with explicit dependencies and target namespaces.
The [root Kustomization](../kubernetes/apollo/flux/apps.yaml) supplies shared configuration; inspect rendered
manifests when changing it because its patches override fields in app files.

## Namespace component

Each namespace directory includes the [namespace component](../kubernetes/apollo/components/namespace/)
and uses its local `namespace.yaml` as a targeted patch to name the Namespace and set Pod Security labels.
Copy an existing namespace's `kustomization.yaml`, including the patch target and `allowNameChange` option.
The component disables Namespace pruning; removing a namespace directory does not delete that Namespace.

Do not set `namespace:` on these directory-level Kustomizations: it would also move their child Flux
Kustomizations out of `flux-system`. Pod Security policy remains explicit per namespace; the shared component
does not infer whether a namespace needs privileged workloads.

## Reconciliation defaults

The root applies deletion and Helm defaults independently of secret substitution:

- Child Kustomizations use `deletionPolicy: WaitForTermination`. Flux deletes managed resources and waits
  for termination, bounded by the child's timeout, before completing Kustomization deletion.
- Helm installs and upgrades use `RemediateOnFailure` with three retries. Failed upgrades use rollback
  remediation, including after the final failed attempt. Installs and upgrades use `crds: CreateReplace`;
  upgrades and rollbacks clean up newly created resources if the operation fails.

The explicit strategies preserve remediation if the controller's `DefaultToRetryOnFailure` feature gate
is enabled. Explicit final-upgrade remediation keeps that policy independent of the retry-count default.
Install final-failure remediation stays unset, retaining the failed installation after retries are exhausted.

HelmRelease defaults are injected as a patch into each child Kustomization, since the root renders the
children rather than their HelmReleases. App versions, values, resource requests, timeouts, and replica
counts remain app-owned. CRD replacement does not make CRD schema changes reversible during rollback.

Declare exceptions on the child Flux Kustomization's `metadata.labels`:

| Label set to `"true"` | Effect |
|---|---|
| `helm-defaults.flux.home.arpa/disabled` | Keep the child's own patch list and Helm policies |
| `helm-crds.flux.home.arpa/disabled` | Keep local Helm CRD policies while receiving remediation defaults |
| `deletion-policy.flux.home.arpa/disabled` | Keep the child's explicit deletion policy |
| `substitution.flux.home.arpa/disabled` | Keep the child's own decryption and substitution settings |

A local field does not override a root default without the corresponding opt-out. A child with its own
`spec.patches` must opt out of Helm defaults, because injecting that list replaces the existing list.
It can then set Helm policy in its HelmRelease or its own patches. Patches in an app's ordinary Kustomize
`kustomization.yaml`, including component patches, are separate and remain available without opting out.

The CRD patch appends to the injected remediation patch list. Opting out of all Helm defaults also skips
this append, preserving a child's custom patches. Cloudflare and UniFi external-dns opt out only of CRD
defaults, retaining local `crds: Skip` policies while receiving shared failure handling.
Cilium and Flux instance opt out of the deletion default and explicitly use `Orphan`, preserving their
resources when their Kustomizations are deleted. `prune: false` alone is insufficient:
`WaitForTermination` requests deletion regardless of that field. Per-resource prune protection, such as
the Namespace component's annotation and the Postgres component's Cluster annotation, still applies.

Validate with `task kubernetes:kubeconform CLUSTER=apollo`, the component tests, and
`flate test all --path ./kubernetes/apollo/flux`; inspect `flate diff all` against the PR base as well.

## References

The namespace component follows
[joryirving's shared Namespace](https://github.com/joryirving/home-ops/tree/main/kubernetes/components/namespace),
adapted to Apollo's centralized Flux namespace. Nested defaults follow
[onedr0p](https://github.com/onedr0p/home-ops/blob/main/kubernetes/flux/cluster/ks.yaml),
[szinn](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/cluster/config/cluster.yaml),
[Mafyuh](https://github.com/Mafyuh/iac/blob/main/kubernetes/flux/cluster.yaml), and
[joryirving](https://github.com/joryirving/home-ops/blob/main/kubernetes/clusters/main/apps.yaml).
[Billimek's root patches](https://github.com/billimek/k8s-gitops/blob/master/setup/flux/cluster/cluster.yaml)
apply directly to HelmReleases in a flatter tree.
Flux documents [Helm remediation](https://fluxcd.io/flux/components/helm/helmreleases/#configuring-failure-handling)
and [Kustomization deletion policies](https://fluxcd.io/flux/components/kustomize/kustomizations/#deletion-policy).
