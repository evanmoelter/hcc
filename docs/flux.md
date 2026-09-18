# Apollo Flux configuration

Apollo resources declare their reconciliation policies in their own manifests. Conftest checks for missing
fields in CI and through `task kubernetes:lint CLUSTER=apollo`. It does not inject values or require opt-out
labels. Change a policy by editing the resource.

## Required declarations

| Resource | Fields |
|---|---|
| HelmRelease | `spec.install.strategy.name`, `spec.install.crds`, `spec.upgrade.strategy.name`, `spec.upgrade.crds`, `spec.upgrade.cleanupOnFail`, `spec.rollback.cleanupOnFail` |
| HelmRelease using `RemediateOnFailure` | `spec.<install or upgrade>.remediation.retries`; upgrades also declare `spec.upgrade.remediation.remediateLastFailure` |
| HelmRelease using `RetryOnFailure` | `spec.<install or upgrade>.strategy.retryInterval` instead of remediation fields |
| Flux Kustomization | `spec.deletionPolicy` |
| Namespace | `metadata.annotations` or `metadata.labels` entry for `kustomize.toolkit.fluxcd.io/prune` |

The [rules](../policy/apollo/required_fields.rego) check that fields contain values, accepting explicit
`false`, zero retries, and alternate policies. Nulls and empty strings, objects, or arrays count as missing.
Kubeconform remains responsible for API types and enum validation. The lint rules require a decision;
they do not judge whether a particular choice is appropriate for the application.

Existing releases use `RemediateOnFailure`, three retries, final upgrade remediation, and upgrade/rollback
cleanup. Explicit strategy names keep failure handling independent of Flux's `DefaultToRetryOnFailure`
feature gate. CRD policies use `CreateReplace`, except the two external-dns releases, which use `Skip`.
CRD replacement does not make CRD changes reversible during rollback.

Kustomizations use `WaitForTermination`, except Cilium and Flux instance, which retain resources with
`prune: false` and `deletionPolicy: Orphan`. Choosing `WaitForTermination` requests deletion even with
`prune: false`, so review both fields when retention matters. Namespaces keep their own pruning metadata
and Pod Security labels. Namespace directory Kustomizations keep child Flux Kustomizations in `flux-system`.

## Validation scope

Lint reads source YAML documents under Apollo's `apps/`, `flux/`, and `components/`, including every document
in satellite files and the bootstrap Flux Kustomization in `flux/config/cluster.yaml`. File names do not
select resources; API group and kind do. Encrypted `*.sops.yaml` and `*.sops.yml` files are excluded.
Talos bootstrap configuration and the frozen `kubernetes/main` tree are outside this policy.

Source checks ensure declarations are visible before rendering; a parent patch cannot satisfy a missing
field. These checks do not detect later patches that overwrite an explicit value. The root retains its
existing decryption/substitution wiring, but adds no Helm or deletion-policy patches. Continue reviewing
the rendered Flux diff for effective behavior, and use kubeconform for schema validation.

Run `mise install aqua:open-policy-agent/conftest` to install the pinned tool, then:

```sh
task kubernetes:lint CLUSTER=apollo
task kubernetes:kubeconform CLUSTER=apollo
python3 -m unittest discover -s tests
flate test all --path ./kubernetes/apollo/flux
```

The lint task runs policy unit tests before checking manifests. CI runs both plus the runner's integration
tests under the required `Kubeconform Success` check. Policy, runner, tool pin, task, and test changes trigger
validation even when no Kubernetes manifest changes.

See [Conftest](https://www.conftest.dev/), Flux's
[Helm failure handling](https://fluxcd.io/flux/components/helm/helmreleases/#configuring-failure-handling), and
[Kustomization deletion policies](https://fluxcd.io/flux/components/kustomize/kustomizations/#deletion-policy).
