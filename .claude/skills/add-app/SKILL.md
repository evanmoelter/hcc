---
name: add-app
description: Use when adding a new application to the cluster — scaffolding a Flux Kustomization plus a HelmRelease under kubernetes/apollo/apps/ ("add X to the cluster", "deploy X", "new app")
---

# Add an application

Scaffolds `kubernetes/apollo/apps/<namespace>/<app>/`. AGENTS.md is already in context and holds the policy; this skill is the procedure. Where they disagree, AGENTS.md wins.

## Before anything else

**New apps go in `kubernetes/apollo/` only.** `kubernetes/main/` is frozen and disable-only. If asked to add an app there, say so and stop rather than adding one.

Check what already exists, because the migration is still landing pieces:

```sh
ls kubernetes/apollo/components/   # postgres, volsync, namespace
ls kubernetes/apollo/apps/
```

If `components/` is absent, the shared-component work from `plans/20260816-talos-migration.md` has not merged. Write the resources into the app directory instead and say that is why.

This whole section is transitional. When Wave 2 removes `kubernetes/main`, delete it along with the frozen-tree rule above, and re-read the rest of this skill against the tree as it stands then.

## Step 1: Research the app

Understand the app before asking anything about it. Most of Step 2 answers itself here, and the questions that survive are sharper for it.

Find out:

- What it does, and what it needs to run: a database, a cache, a broker, hardware, a second network interface.
- Whether it publishes its own Helm chart, and whether a rootless image exists in [home-operations/containers](https://github.com/home-operations/containers).
- What it stores and where: a config directory, a database, both, or nothing worth keeping.
- Its documented environment variables, ports, and expected user and group.

**Ask the operator for community examples.** Many home Kubernetes users publish their configuration and this repo leans on those repos heavily, but an agent has no automated way to find them yet. A working example from a comparable cluster settles what upstream documentation leaves open: real security contexts, real probe timings, and which settings actually matter.

Report what the research found before moving on. If it contradicts something already specified, say so rather than quietly picking one.

## Step 2: Gather what research did not settle

Ask with AskUserQuestion. Do not guess any of these, and do not re-ask what Step 1 answered.

1. **Name and namespace.** Namespace from the existing list, not a new one, unless asked.
2. **Chart.** The app's own chart when it publishes a usable one, `app-template` wrapping a single image otherwise. Say which the research found and let the operator confirm; this choice shapes the whole `helmrelease.yaml`.
3. **Image and tag**, on the `app-template` path. [home-operations/containers](https://github.com/home-operations/containers) first, an upstream image second. Pin the tag.
4. **Port**, and whether it gets a route: internal Gateway, external Gateway, both, or none.
5. **Persistence.** Does it hold state worth backing up?
6. **Database.** Postgres?
7. **Secrets.** Which values, and the 1Password item and exact field names. Never invent field names.
8. **Config file.** Only if the chart cannot express the setting in Helm values.

## Step 3: Lay out the directory

```
<app>/
  ks.yaml
  app/
    kustomization.yaml
    ocirepository.yaml
    helmrelease.yaml
    externalsecret.yaml     only if secrets
```

Add `ks-backup.yaml` and a `backup/` directory only when the backup has a failure mode worth suspending independently of the workload. A component-supplied `ReplicationSource` does not need one.

### ks.yaml

```yaml
---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app mealie
  namespace: flux-system
spec:
  targetNamespace: default
  components:
    - ../../../../components/volsync
  dependsOn:
    - name: longhorn
  path: ./kubernetes/apollo/apps/default/mealie/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  interval: 30m
  postBuild:
    substitute:
      APP: *app
```

- `dependsOn` lists storage and identity. Components carry their own, so a `postgres` component means you do not write `cloudnative-pg` yourself.
- `postBuild.substitute.APP` is required whenever any component is used.
- Set `wait: true` only when another Kustomization depends on this one and this one defines no health checks. Otherwise leave it off.
- Do not set `retryInterval`, `timeout`, or HelmRelease remediation. The root `cluster-apps` Kustomization defaults them, and a local value is silently overridden.

### app/ocirepository.yaml and helmrelease.yaml

Charts come from an `OCIRepository` referenced by `chartRef`, not a `HelmRepository`. That holds for either chart choice; only `url` and `ref.tag` differ.

```yaml
---
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/source.toolkit.fluxcd.io/ocirepository_v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: &app mealie
spec:
  interval: 15m
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 5.1.0
  url: oci://ghcr.io/bjw-s-labs/helm/app-template
```

For an app's own chart, keep the shape and change the last two fields to that chart's registry and version.

If the chart is published only to an HTTP repository and not OCI, stop and say so. That needs a `HelmRepository`, which is the shape Apollo is moving away from, so it deserves a deliberate exception rather than a silent one.

The HelmRelease points at it with `chartRef: {kind: OCIRepository, name: *app}`. Bump the `$schema` comment with the chart version. `app-template` publishes its own HelmRelease schema; a vendor chart usually does not, so use the generic `helm.toolkit.fluxcd.io/helmrelease_v2.json` rather than pointing at an unrelated one.

### Security context

New workloads run as UID and GID 568:

```yaml
pod:
  securityContext:
    runAsUser: 568
    runAsGroup: 568
    runAsNonRoot: true
    fsGroup: 568
    fsGroupChangePolicy: OnRootMismatch
containers:
  app:
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities: { drop: ["ALL"] }
```

If the image will not tolerate it, loosen the single setting that blocks it and say which one and why. Do not drop the block.

### Resources

CPU and memory requests, memory limit, no CPU limit.

## Step 4: Register it

Add the app's `ks.yaml` to the namespace's `kustomization.yaml`. **Flux cannot see an unregistered app**, and nothing else in the pipeline catches this.

## Step 5: Validate

```sh
task kubernetes:kubeconform CLUSTER=apollo
```

Kubeconform checks schemas, not Helm values. For anything non-trivial, render it too — see the flux rendering command in AGENTS.md.

## Conventions worth not rediscovering

| Rule | Why |
|---|---|
| `# yaml-language-server: $schema=` on every manifest | Editor and CI validation; the URL tracks the chart version |
| YAML anchors: `name: &app mealie` | The name appears five or more times per app |
| `${SECRET_DOMAIN}`, `${TIMEZONE}` from `flux/vars/` | Never write the literals |
| Secrets as env vars, via `envFrom.secretRef` or `secretKeyRef` | Hostnames, database names, and bucket paths stay readable in a diff |
| Config in Helm values | `configMapGenerator` only when the chart cannot express it |
| Very few code comments | See AGENTS.md; machine-read annotations are exempt, and a documented third-party limitation may earn one |

## Things this skill will not do

- Write plaintext into a `*.sops.yaml`. Instead, create the file with placeholders and ask the operator to encrypt with `task sops:encrypt`.
- `kubectl apply` the result. Flux reconciles it from git.
- Add an app to `kubernetes/main/`.
