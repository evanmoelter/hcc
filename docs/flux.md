# Apollo Flux configuration

Apollo resources declare their reconciliation policies in their own manifests. Conftest checks required
fields and the pruning/deletion combination in CI and through `task kubernetes:lint CLUSTER=apollo`.
It does not inject values. Change a policy by editing the resource.

## Required declarations

| Resource | Fields |
|---|---|
| HelmRelease | `spec.install.strategy.name`, `spec.upgrade.strategy.name`, `spec.upgrade.cleanupOnFail` |
| HelmRelease using `RemediateOnFailure` | `spec.<install or upgrade>.remediation.retries`; upgrades also declare `spec.upgrade.remediation.remediateLastFailure` |
| HelmRelease using `RetryOnFailure` | `spec.<install or upgrade>.strategy.retryInterval` instead of remediation fields |
| HelmRelease upgrading with `RemediateOnFailure` and rollback remediation | `spec.rollback.cleanupOnFail`; omitted `spec.upgrade.remediation.strategy` means `rollback` |
| Flux Kustomization | `spec.deletionPolicy` |
| Namespace | `metadata.annotations` or `metadata.labels` entry for `kustomize.toolkit.fluxcd.io/prune` |

The [rules](../policy/apollo/required_fields.rego) check that fields contain values, accepting explicit
`false`, zero retries, and alternate policies. Nulls and empty strings, objects, or arrays count as missing.
Kubeconform remains responsible for API types and enum validation. Retry counts and cleanup booleans
remain app-specific choices. Rollback settings are optional for `RetryOnFailure` and `uninstall` remediation.

Existing releases use `RemediateOnFailure`, three retries, final upgrade remediation, and upgrade/rollback
cleanup. Explicit strategy names keep failure handling independent of Flux's `DefaultToRetryOnFailure`
feature gate. CRD policy fields are optional: declare them where a chart's CRD lifecycle needs them.
Chart values controlling templated CRDs are separate from Flux's handling of the chart's `crds/` directory.
Existing chart-specific CRD declarations remain, including `Skip` for the two external-dns releases.
CRD replacement does not make CRD changes reversible during rollback.

Kustomizations use `WaitForTermination`, except Cilium and Flux instance, which retain resources with
`prune: false` and `deletionPolicy: Orphan`. Choosing `WaitForTermination` requests deletion even with
`prune: false`, so review both fields when retention matters. Namespaces keep their own pruning metadata
and Pod Security labels. Namespace directory Kustomizations keep child Flux Kustomizations in `flux-system`.

## Pruning and deletion guard

Lint rejects `prune: false` with `deletionPolicy: Delete` or `WaitForTermination`. Both policies delete
resources when the owning Kustomization is deleted, despite disabled pruning. `Orphan` and `MirrorPrune`
are allowed without an exception; with `prune: true`, all schema-valid deletion policies are allowed.

If retaining resources removed from git while deleting them with their owner is intentional, set this
annotation on the owning Flux Kustomization with a nonblank explanation:

```yaml
metadata:
  annotations:
    lint.flux.home.arpa/delete-without-prune-reason: Retain removed resources until the owner is deleted.
```

The explanation exempts only this combination check. Required declarations still apply. No current Apollo
resource needs the exception.

## Validation scope

Lint reads source YAML documents under Apollo's `apps/`, `flux/`, and `components/`, including every document
in satellite files and the bootstrap Flux Kustomization in `flux/config/cluster.yaml`. File names do not
select resources; API group and kind do. Encrypted `*.sops.yaml` and `*.sops.yml` files are excluded.
Talos bootstrap configuration and the frozen `kubernetes/main` tree are outside this policy.

Source checks ensure declarations are visible before rendering; a parent patch cannot satisfy a missing
field. These checks do not detect later patches that overwrite an explicit value. The root retains its
existing decryption/substitution wiring, but adds no Helm or deletion-policy patches. Continue reviewing
the rendered Flux diff for effective configuration, and use kubeconform for schema validation. Rendering
does not exercise Helm failure cleanup, CRD lifecycle operations, or Kustomization deletion behavior.

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
