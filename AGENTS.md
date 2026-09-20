# AGENTS.md

Guidance for AI agents working in this repository. [README.md](./README.md) describes what the cluster is; this file describes how to change it.

This is a GitOps repository for a home Kubernetes cluster. Flux applies whatever is committed here, so the way to change the cluster is to change these files.

## Ground rules

1. **Read-only against the live cluster.** Inspect freely with `kubectl get`, `describe`, `logs`, `flux get`, `k9s`, and `stern`. Anything that changes cluster state (`apply`, `delete`, `patch`, `scale`, `rollout restart`, `flux reconcile`, `flux suspend`, `talosctl`) needs the operator's explicit approval first. Propose the command and say what it will do.
2. **Never `kubectl apply` over Flux.** Everything under `kubernetes/` is reconciled from git. A hand-applied manifest either gets reverted on the next reconcile or survives as drift that no file explains. Change the file, commit it, and let Flux converge.
3. **Never write plaintext secrets.** Files matching `*.sops.yaml` are encrypted with age. Editing one in place commits secrets to a public repository. The operator is responsible for keeping secrets up to date.
4. **Read the plan before implementing.** `plans/` holds design docs written ahead of the work. If a plan covers the task, follow it. If it is stale, say so instead of improvising around it.
5. **Check `docs/` for settled facts.** `docs/` describes how things are; `plans/` describes how they will change. Addressing, VLANs, and firewall rules live in [docs/networking.md](./docs/networking.md), so take them from there rather than from a plan that may predate the decision. When a plan's work lands, keep current architecture and reusable implementation guidance in `docs/`. Preserve the full plan and its execution record in `plans/done/`.

## Two cluster trees

| Path | Cluster | Rule |
|---|---|---|
| `kubernetes/apollo/` | Talos, the cluster going forward | where new work goes |
| `kubernetes/main/` | k3s, serving remaining apps | frozen; disable-only |

Apollo's platform and integration documentation is indexed in [docs/index.md](./docs/index.md).
Mealie is migrated to Apollo; its [completed cutover record](./plans/done/20260918-mealie-migration.md)
preserves verification and cleanup evidence. New platform components and new apps go in `kubernetes/apollo/`.
Changes to an app still served by `kubernetes/main/` land in that tree, and each one is worth weighing
against the migration: work that Wave 1 will throw away is usually not worth doing.

## How an app is laid out

For new apps, use the repository's [add-apollo-app skill](./.agents/skills/add-apollo-app/SKILL.md).
Existing apps moving from `main` follow the migration plan instead.

Apollo apps live under `kubernetes/apollo/apps/<namespace>/<app>/`. A PVC-backed app uses:

```
mealie/
  ks.yaml                        app Flux Kustomization
  ks-storage.yaml                preflight, storage, backup Kustomizations (separate YAML documents)
  app/
    kustomization.yaml
    helmrelease.yaml             bjw-s app-template, pinned chart version
  storage/
    kustomization.yaml
    pvc.yaml                     app-owned PVC, explicit dataSourceRef when restored
```

To add an app:

1. Create the directory following the shape above.
2. Register `ks.yaml` and its satellite files in the namespace's `kustomization.yaml`. Flux cannot see unregistered resources.
3. List every dependency in `dependsOn`. Storage, database, and identity (`longhorn`, `cloudnative-pg`, `authentik`) all belong there, or the first reconcile races.
4. Pass `APP: *app` through `postBuild.substitute` for VolSync. Apollo uses the
   [lifecycle components](./kubernetes/apollo/components/volsync/), including a required preflight during recovery;
   new PVCs omit restore configuration. The old cluster retains its template.
5. Run the [applicable validation](#validating-changes) before opening a PR.

## Community resources

There is a huge community of home Kubernetes users, many of whom have public repos with their config. This repo heavily relies on these community resources.

The [community-discovery skill](./.agents/skills/community-discovery/SKILL.md) researches public home
Kubernetes repositories for apps and platform work. Research those and upstream documentation
before asking the operator for resources; ask when an unresolved choice needs their input.

Two of them are load-bearing here:

- [home-operations/k8s-schemas](https://github.com/home-operations/k8s-schemas) builds the JSON schemas that the `$schema=` comments and `task kubernetes:kubeconform` validate against.
- [home-operations/containers](https://github.com/home-operations/containers) builds rootless application containers. For a workload with no app-specific Helm chart, prefer one of these images, then an upstream image, and only fall back to a custom build when neither does what the app needs.

## Patterns

Guidelines rather than rules. Follow them where they fit. If one takes jumping through hoops to implement, the extra complexity is probably not worth it, so skip it and say why.

### Manifest conventions

New manifests should open with a `# yaml-language-server: $schema=` comment, and the schema URL tracks the chart version, so bumping one means bumping the other. Use YAML anchors (`name: &app mealie`) instead of repeating the app name. Pin image tags and digests so Renovate can bump them. Take `${SECRET_DOMAIN}` and `${TIMEZONE}` from `kubernetes/*/flux/vars/` rather than writing literals.

Keep one chart `OCIRepository` per app beside its `HelmRelease`, so apps can upgrade independently.
Set both `spec.ref.tag` and `spec.ref.digest`: the tag identifies the version for readers and Renovate;
Flux pulls the digest, which takes precedence. Update both together on version bumps and retain signature verification where configured.

Declare Helm CRD lifecycle fields where the chart needs them; chart values managing templated CRDs are separate.

### Config in git, credentials in secrets

Configure an app through the chart's Helm values where it supports them, so the whole configuration sits in the HelmRelease. Fall back to a committed file rendered with `configMapGenerator` only when the app needs one the chart cannot produce, as Home Assistant does with `configs/configuration.yaml`.

Credentials arrive as environment variables from a secret, through `envFrom.secretRef` for a bundle or `secretKeyRef` for a single value like the CNPG connection URI. Keep everything else out of the secret so hostnames, database names, and bucket paths stay readable in a diff. If an app wants a secret inside a config file and gives you no way to interpolate one, use an `ExternalSecret` to template the file once Apollo's `onepassword-store` is Ready.

### One Flux Kustomization per lifecycle

Use a separate Flux Kustomization for each lifecycle. Related Kustomizations may share a satellite file,
such as preflight, storage, and backup in `ks-storage.yaml`. Point each at its own resource directory or a shared
base and express the actual dependency order: preflight → storage → app → backup.

### Non-root with a hardened container context

New workloads run as UID and GID 568, with `runAsNonRoot`, `fsGroup: 568`, and `fsGroupChangePolicy: OnRootMismatch` on the pod, and `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, and `capabilities.drop: ["ALL"]` on the container. Mealie, Home Assistant, and Node-RED are built this way. Some images will not tolerate it. Loosen the one setting that blocks the app rather than dropping the whole block.

### CPU requests, memory limits

Set CPU and memory requests along with a memory limit, and leave the CPU limit off by default. Throttling a workload through a short busy period usually costs more than it saves on a cluster this size.

Cap CPU where a burst would cost more than the throttling does, such as a background reconciler sharing nodes with latency-sensitive workloads. Flux's controllers carry a `2000m` limit for that reason.

## Secrets

- Avoid reading secrets from anywhere. Instead, ask the operator to check them for you.
- Do not leak secrets or potentially sensitive information in any externally visible output (e.g. commits, docs, PR descriptions, etc.).
- App and cluster secrets live in `*.sops.yaml` and 1Password (synced with ESO).
  - SOPS: You should never decrypt or edit these files directly. Instead, ask the operator to make the changes for you. For new secrets files, create a file with placeholder values and encrypt with `task sops:encrypt`. Note that only `data` and `stringData` are encrypted, so the rest of the file stays reviewable in a diff.
  - 1Password: You should never read or write secrets from/to 1Password directly. For new secrets, you can suggest naming/paths and the user will create the entry for you.

## Validating changes

```sh
task kubernetes:kubeconform CLUSTER=main    # schema validation, same as CI
task kubernetes:kubeconform CLUSTER=apollo  # the same, against the Apollo tree
task kubernetes:lint CLUSTER=apollo         # Conftest policies and their tests
task talos:render CLUSTER=apollo            # for Talos changes; renders machine configs, no hardware needed
```

A Flux change is worth rendering as well, since kubeconform validates schemas but not Helm values:

```sh
flate test all --path ./kubernetes/apollo/flux    # renders every Kustomization and HelmRelease
flate build hr --path ./kubernetes/apollo/flux cilium
```

Every task that reads a cluster tree requires a `CLUSTER` variable naming a directory under `kubernetes/`. It doubles as the kubectl context, so a cluster's context must be named after it: tasks pass `--context {{.CLUSTER}}` and never a kubeconfig path. Never export `CLUSTER` from the shell, since Task reads variables from the environment and would hand every cluster-scoped task a silent default. There is deliberately no default: while two trees exist, a default silently points writes at the wrong one, and `sops:encrypt` in particular would report success having encrypted nothing. Tasks refuse to run when it is unset, or when no context matches.

CI starts `kubernetes-validation.yaml` and `flux-diff.yaml` for PRs targeting any branch, including stacked PRs.
Both workflows run when a PR is opened, updated with commits, reopened, or edited. Edits include title and
description changes as well as base-branch changes. Change detection includes deleted files and compares
against the PR event's base commit. Manifest diffs use that same baseline, keeping each stacked PR scoped
to its immediate parent.

Kubernetes Validation runs schema checks for both clusters and component/policy tests when Kubernetes
manifests, validation scripts, policies, tool pins, the Kubernetes taskfile, tests, or its workflow change;
otherwise those jobs skip. `flux-diff.yaml` runs its rendering jobs when Kubernetes manifests, its workflow,
or its helper scripts change. It renders `main` with flux-local and Apollo with
[flate](https://github.com/home-operations/flate). Apollo validation renders the full tree; only the diff
uses a baseline. Both rendering tools output the manifest delta for review. Aggregate jobs report the
required checks even when validation jobs skip because no relevant files changed; the Flux aggregate
stops when its workflow is cancelled.

## Code style

### Code Comments

I prefer to avoid code comments unless absolutely necessary.

Every comment is a claim the compiler never checks. It can be wrong when written, or go stale as the code drifts. A misleading comment leaves the reader worse off than no comment at all.

- Let the code speak for itself. Prefer a verbose name over an explanatory comment. If a block needs a comment to be readable, try to refactor it instead.
- No comments about rejected approaches or removed code.
- Do not document context that belongs in a PR. Comments are not the right place to answer a code review comment.
- You can document third-party limitations where necessary. Non-obvious behavior in a an app/package we don't control is sometimes worth a comment. Link the upstream bug report so we know when the workaround can go.
- If you're not 100% sure about a comment, ask me.

If you must add a comment:
- Keep it extremely short. A long comment costs the reader the time it was meant to save.
- Wrap at 120 characters. Biome formats code, not comments.

Caveats:
- some comments have leaked into the codebase. Just because a comment currently exists doesn't mean it's accurate or an acceptable pattern to follow.
- machine-read annotations and directives are outside this policy.

## Commits and pull requests

Graphite is used to manage the branch/commit/PR lifecycle. The operator's Graphite skills document the current best practices.

Use Graphite for branch and PR management. `gt sync` and `gt submit` are authorized (without `--force`),
including their normal rebasing and remote-history updates.

Never use `gt sync --force`, `gt submit --force`, or raw Git force-push commands. If the normal Graphite
commands cannot complete, explain the problem and ask the operator how to proceed.

## Gotchas

Add new ones here as they are discovered. Remove existing ones when they have been solved.

### Empty VolSync backups

Seed a file before expecting the first restic snapshot. Apollo's mover skips an empty directory successfully,
so a successful sync alone does not establish a restore point. An init container can touch a placeholder.
The old-cluster `mealie` and `paperless-sftp` workloads use this pattern.

### Stopping a stuck CNPG pod takes two steps

Hibernation alone will not stop it. Suspend the Flux Kustomization, then scale the CNPG operator to zero, or the operator recreates the pod as fast as you remove it. Reverse the order to restore.

### Longhorn ignores disk speed when placing replicas

Keep slow disks out of the pool rather than trusting the scheduler to avoid them.

## Tooling

Local tools are installed/managed with Mise. Everything should be pinned in [`mise.toml`](./mise.toml). Use mise CLI to install/update tools.

Prefer `task <group>:<name>` over raw commands for frequently used tasks; `task` on its own lists what exists.

Talos machine configuration is managed with `topf`, pinned in `mise.toml`, from `kubernetes/<cluster>/bootstrap/talos/`. `task talos:render` validates a config with no hardware; `apply`, `upgrade`, and `reset` all touch nodes and prompt first. Kubernetes upgrades use `talosctl upgrade-k8s` directly, because `topf` does not wrap them.

## Keeping these docs current

Keep the documentation catalog in [docs/index.md](./docs/index.md). Shared repository conventions and
validation commands belong here; skills should link to those sources rather than repeat them.
Document major service areas in `docs/`; keep app-specific cutover details in their migration plans.

Part of your job is keeping this doc and the README up to date.

Document decisions, non-obvious behavior, and operational context that cannot be inferred from the manifests.
Avoid restating configuration or duplicating general procedures. Keep version pins in code; mention versions
in docs only when they explain a compatibility constraint or historical verification result.

Prefer lint rules for conventions that should be enforced widely, keeping the rules and their tests as the source of truth.

Propose an edit when you:

- Learn a convention these docs do not state, or find one they state wrongly.
- Add or remove something the README describes: a node, an app, a platform component, a task worth knowing about.
- Hit a failure worth a new entry under Gotchas, or fix one that is already listed. Solved gotchas get removed rather than left behind as history.

Put the doc change in the same PR as the work it describes. Write the docs for the state after the PR is merged and deployed, so deployment alone does not require a follow-up documentation PR.

Two caveats.
- Be selective about what deserves to be documented. If these docs get too detailed, they will become a maintenance burden.
- Propose rather than assume. If you are unsure whether something is a real rule or just how one app happens to be written, ask the operator instead of promoting an accident into policy.
