# AGENTS.md

Guidance for AI agents working in this repository. [README.md](./README.md) describes what the cluster is; this file describes how to change it.

This is a GitOps repository for a home Kubernetes cluster. Flux applies whatever is committed here, so the way to change the cluster is to change these files.

## Ground rules

1. **Read-only against the live cluster.** Inspect freely with `kubectl get`, `describe`, `logs`, `flux get`, `k9s`, and `stern`. Anything that changes cluster state (`apply`, `delete`, `patch`, `scale`, `rollout restart`, `flux reconcile`, `flux suspend`, `talosctl`) needs the operator's explicit approval first. Propose the command and say what it will do.
2. **Never `kubectl apply` over Flux.** Everything under `kubernetes/` is reconciled from git. A hand-applied manifest either gets reverted on the next reconcile or survives as drift that no file explains. Change the file, commit it, and let Flux converge.
3. **Never write plaintext secrets.** Files matching `*.sops.yaml` are encrypted with age. Editing one in place commits secrets to a public repository. The operator is responsible for keeping secrets up to date.
4. **Read the plan before implementing.** `plans/` holds design docs written ahead of the work. If a plan covers the task, follow it. If it is stale, say so instead of improvising around it.
5. **Check `docs/` for settled facts.** `docs/` describes how things are; `plans/` describes how they will change. Addressing, VLANs, and firewall rules live in [docs/networking.md](./docs/networking.md), so take them from there rather than from a plan that may predate the decision. When a plan's work lands, the durable result belongs in `docs/` and the plan keeps only a pointer.

## Two cluster trees

| Path | Cluster | Rule |
|---|---|---|
| `kubernetes/apollo/` | Talos, the cluster going forward | where new work goes |
| `kubernetes/main/` | k3s, serving everything today | frozen; disable-only |

`kubernetes/apollo/` holds only `bootstrap/talos/` so far; it has no Flux tree, so no app can be deployed there yet. Until it has one, changes to running apps still land in `kubernetes/main/`, and each one is worth weighing against the migration: work that Wave 1 will throw away is usually not worth doing.

## How an app is laid out

Each app is a directory under `kubernetes/<cluster>/apps/<namespace>/<app>/`:

```
mealie/
  ks.yaml                        Flux Kustomization: dependsOn, targetNamespace, postBuild vars
  ks-backup.yaml                 second Kustomization for the backup config
  app/
    kustomization.yaml
    helmrelease.yaml             bjw-s app-template, pinned chart version
    cluster.yaml                 CNPG Cluster, one per app
    pvc.yaml
    secret.sops.yaml
  backup/
    data-volsync-r2.yaml         VolSync ReplicationSource
    data-volsync-r2.sops.yaml    restic repository credentials
```

To add an app:

1. Create the directory following the shape above.
2. Register its `ks.yaml` in the namespace's `kustomization.yaml`. Flux cannot see an unregistered app.
3. List every dependency in `dependsOn`. Storage, database, and identity (`longhorn`, `cloudnative-pg`, `authentik`) all belong there, or the first reconcile races.
4. Pass `APP: *app` through `postBuild.substitute` if the app uses the shared VolSync template.
5. Validate with `task kubernetes:kubeconform` before opening a PR.

## Community resources

There is a huge community of home Kubernetes users, many of whom have public repos with their config. This repo heavily relies on these community resources.

An automated way for agents to discover these resources is coming soon. For now, ask the operator to help you find relevant repos/resources, especially when implementing new apps.

Two of them are load-bearing here:

- [home-operations/k8s-schemas](https://github.com/home-operations/k8s-schemas) builds the JSON schemas that the `$schema=` comments and `task kubernetes:kubeconform` validate against. It serves them at `k8s-schemas.home-operations.com`; this repo still points at the older `kubernetes-schemas.pages.dev`. Check there first when a CRD has no schema or fails validation.
- [home-operations/containers](https://github.com/home-operations/containers) builds rootless application containers. For a workload with no app-specific Helm chart, prefer one of these images, then an upstream image, and only fall back to a custom build when neither does what the app needs.

## Patterns

Guidelines rather than rules. Follow them where they fit. If one takes jumping through hoops to implement, the extra complexity is probably not worth it, so skip it and say why.

### Manifest conventions

New manifests should open with a `# yaml-language-server: $schema=` comment, and the schema URL tracks the chart version, so bumping one means bumping the other. Use YAML anchors (`name: &app mealie`) instead of repeating the app name. Pin chart and image versions so Renovate can bump them. Take `${SECRET_DOMAIN}` and `${TIMEZONE}` from `kubernetes/*/flux/vars/` rather than writing literals.

### Config in git, credentials in secrets

Configure an app through the chart's Helm values where it supports them, so the whole configuration sits in the HelmRelease. Fall back to a committed file rendered with `configMapGenerator` only when the app needs one the chart cannot produce, as Home Assistant does with `configs/configuration.yaml`.

Credentials arrive as environment variables from a secret, through `envFrom.secretRef` for a bundle or `secretKeyRef` for a single value like the CNPG connection URI. Keep everything else out of the secret so hostnames, database names, and bucket paths stay readable in a diff. If an app wants a secret inside a config file and gives you no way to interpolate one, do not build the mechanism yourself. ESO arrives soon, and an `ExternalSecret` can template a whole config file with its secrets in place; expect that to become the answer for apps that cannot interpolate their own.

### One Flux Kustomization per lifecycle

Split an app into `ks.yaml` plus a satellite for anything with a different failure mode: `ks-backup.yaml`, `ks-sftp.yaml`, `ks-restore.yaml`, `ks-cluster.yaml`. Point the satellite at its own subdirectory and give it a `dependsOn` back to the app. A backup can then fail, or be suspended for a cutover, without disturbing the workload that serves traffic.

### Non-root with a hardened container context

New workloads run as UID and GID 568, with `runAsNonRoot`, `fsGroup: 568`, and `fsGroupChangePolicy: OnRootMismatch` on the pod, and `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, and `capabilities.drop: ["ALL"]` on the container. Mealie, Home Assistant, and Node-RED are built this way. Some images will not tolerate it. Loosen the one setting that blocks the app rather than dropping the whole block.

### CPU requests, memory limits

Set CPU and memory requests along with a memory limit, and leave the CPU limit off. Throttling a workload through a short busy period costs more than it saves on a cluster this size.

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
task talos:render CLUSTER=apollo            # for Talos changes; renders machine configs, no hardware needed
```

Every task that reads a cluster tree requires a `CLUSTER` variable naming a directory under `kubernetes/`. It doubles as the kubectl context, so a cluster's context must be named after it: tasks pass `--context {{.CLUSTER}}` and never a kubeconfig path. Never export `CLUSTER` from the shell, since Task reads variables from the environment and would hand every cluster-scoped task a silent default. There is deliberately no default: while two trees exist, a default silently points writes at the wrong one, and `sops:encrypt` in particular would report success having encrypted nothing. Tasks refuse to run when it is unset, or when no context matches.

CI runs `kubeconform.yaml` and `flux-diff.yaml` on PRs that touch `kubernetes/**`, once per cluster in each workflow's matrix. Kubeconform is filtered by path and does not start otherwise; flux-local always starts but skips its test and diff jobs when nothing under `kubernetes/` changed. The flux-diff output shows the rendered manifest delta, which is useful to review when reviewing a Flux change. A new cluster tree needs an entry added to both matrices before CI validates it.

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

Never force push a branch. If the repo gets into a bad state, propose a fix for the operator (who is a git expert) to run manually.
`gt sync` is generally safe and can be run frequently. `gt sync --force` and `gt submit --force` are not safe.

## Gotchas

Add new ones here as they are discovered. Remove existing ones when they have been solved.

### VolSync fails on an empty PVC

A restic `ReplicationSource` over a directory with no files errors out instead of taking an empty snapshot. Give the workload an init container that touches a placeholder file. Both `mealie` and `paperless-sftp` do this.

### Stopping a stuck CNPG pod takes two steps

Hibernation alone will not stop it. Suspend the Flux Kustomization, then scale the CNPG operator to zero, or the operator recreates the pod as fast as you remove it. Reverse the order to restore.

### Longhorn ignores disk speed when placing replicas

Keep slow disks out of the pool rather than trusting the scheduler to avoid them.

## Tooling

Local tools are installed/managed with Mise. Everything should be pinned in [`mise.toml`](./mise.toml). Use mise CLI to install/update tools.

Prefer `task <group>:<name>` over raw commands for frequently used tasks; `task` on its own lists what exists.

Talos machine configuration is managed with `topf`, pinned in `mise.toml`, from `kubernetes/<cluster>/bootstrap/talos/`. `task talos:render` validates a config with no hardware; `apply`, `upgrade`, and `reset` all touch nodes and prompt first. Kubernetes upgrades use `talosctl upgrade-k8s` directly, because `topf` does not wrap them.

## Keeping these docs current

Part of your job is keeping this doc and the README up to date.

Propose an edit when you:

- Learn a convention these docs do not state, or find one they state wrongly.
- Add or remove something the README describes: a node, an app, a platform component, a task worth knowing about.
- Hit a failure worth a new entry under Gotchas, or fix one that is already listed. Solved gotchas get removed rather than left behind as history.

Put the doc change in the same PR as the work it describes. A follow-up PR for it rarely gets written.

Two caveats.
- Be selective about what deserves to be documented. If these docs get too detailed, they will become a maintenance burden.
- Propose rather than assume. If you are unsure whether something is a real rule or just how one app happens to be written, ask the operator instead of promoting an accident into policy.
