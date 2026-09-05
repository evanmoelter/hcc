---
name: add-app
description: Use when adding a new application to the cluster — scaffolding a Flux Kustomization plus a HelmRelease under kubernetes/apollo/apps/ ("add X to the cluster", "deploy X", "new app")
---

# Add an application

Scaffolds `kubernetes/apollo/apps/<namespace>/<app>/`. Read [AGENTS.md](../../../AGENTS.md) first; this skill is the procedure, that file is the policy.

## Before anything else

**New apps go in `kubernetes/apollo/` only.** `kubernetes/main/` is frozen and disable-only. If asked to add an app there, say so and stop rather than adding one.

Check what already exists, because the migration is still landing pieces:

```sh
ls kubernetes/apollo/components/   # postgres, volsync, namespace
ls kubernetes/apollo/apps/
```

If `components/` is absent, the shared-component work from `plans/20260816-talos-migration.md` has not merged. Write the resources into the app directory instead and say that is why.

## Step 1: Gather what you cannot infer

Ask with AskUserQuestion for anything not given. Do not guess any of these.

1. **Name and namespace.** Namespace from the existing list, not a new one, unless asked.
2. **Image and tag.** Check [home-operations/containers](https://github.com/home-operations/containers) first, an upstream image second. Pin the tag.
3. **Port**, and whether it gets a route: internal Gateway, external Gateway, both, or none.
4. **Persistence.** Does it hold state worth backing up?
5. **Database.** Postgres?
6. **Secrets.** Which values, and the 1Password item and exact field names. Never invent field names.
7. **Config file.** Only if the chart cannot express the setting in Helm values.

## Step 2: Lay out the directory

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

Charts come from an `OCIRepository` referenced by `chartRef`, not a `HelmRepository`:

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

The HelmRelease points at it with `chartRef: {kind: OCIRepository, name: *app}`. Bump the `$schema` comment with the chart version.

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

## Step 3: Register it

Add the app's `ks.yaml` to the namespace's `kustomization.yaml`. **Flux cannot see an unregistered app**, and nothing else in the pipeline catches this.

## Step 4: Validate

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
| No code comments | See AGENTS.md; machine-read annotations are exempt |

## Things this skill will not do

- Write plaintext into a `*.sops.yaml`. Create the file with placeholders and ask the operator to encrypt with `task sops:encrypt`.
- `kubectl apply` the result. Flux reconciles it from git.
- Add an app to `kubernetes/main/`.
