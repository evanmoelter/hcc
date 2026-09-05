# Home Compute Cluster (hcc)

> [!WARNING]
> **Migration in progress; this README is under construction.** The cluster is moving from ansible-managed k3s to Talos. The new cluster, Apollo, is designed but not yet built, so the workloads described here still run on the old cluster under `kubernetes/main`. Sections marked as placeholders get filled in as the migration proceeds. Where this README and [plans/20260816-talos-migration.md](./plans/20260816-talos-migration.md) disagree, the plan wins.

Kubernetes cluster(s) running the household's services on bare metal in the basement: home automation, recipes, documents, and car telemetry. Flux reconciles everything from this repository using the guiding principles of GitOps.

## Migration status


|              | `kubernetes/main`              | `kubernetes/apollo` |
| ------------ | ------------------------------ | ------------------- |
| Distribution | k3s on Debian, ansible-managed | Talos               |
| Status       | serving all apps; frozen       | Talos machine config only; no Flux tree yet |
| Fate         | deleted in Wave 2              | the cluster         |


Apps cut over one at a time from verified backups. `kubernetes/main` stays intact for rollback until the last app has moved. [plans/20260816-talos-migration.md](./plans/20260816-talos-migration.md) holds the full design: node topology, storage, networking, and per-app data migration.

## Hardware

> Placeholder. Filled in as nodes are provisioned.



## What runs here

> Placeholder. Filled in as apps are deployed.



## Day-2 operations

Tools are pinned in [mise.toml](./mise.toml) and environment variables in [.envrc](./.envrc). `mise install` and `direnv allow` set up a workstation.

```sh
task                                        # list every task
flux get kustomizations -A                  # what is reconciling, and what is not
flux get helmreleases -A
task flux:reconcile CLUSTER=main            # pull changes from git now, rather than waiting
task kubernetes:kubeconform CLUSTER=main    # validate manifests the way CI does
task kubernetes:resources                   # gather cluster state for troubleshooting
task talos:render CLUSTER=apollo            # render Talos machine configs, no hardware needed
task talos:kubeconfig CLUSTER=apollo        # refresh Apollo's admin kubeconfig
kubectx main | kubectx apollo               # switch clusters
k9s                                         # poke around
stern -n default <app>                      # tail logs
```

Every task that reads a cluster tree needs `CLUSTER`, naming a directory under `kubernetes/`. There is no default while two clusters exist.

Each cluster keeps its own `kubeconfig-<cluster>` at the repo root, and [.envrc](./.envrc) merges them into one `KUBECONFIG` list so `kubectx` switches between them by context name. `./kubeconfig` is a stub holding nothing but `current-context`; it exists so `kubectx` records the selection there rather than editing a generated per-cluster file. Tasks ignore the selection and use their own `CLUSTER`, so `task flux:reconcile CLUSTER=main` hits main whatever `kubectx` says.

Apollo's kubeconfig is a temporary admin certificate, so `task talos:kubeconfig CLUSTER=apollo` reissues it. It defaults to 168h; `validity=` takes a Go duration, which has no day unit.

> Recovery runbooks: placeholder. Filled in as each one is exercised.



## Bootstrapping

> Placeholder. Filled in as the cluster is built.



## Repository layout

```
kubernetes/main/       old cluster manifests: bootstrap/, flux/, apps/, templates/
kubernetes/apollo/     new cluster: bootstrap/talos/ holds topf.yaml and its machine config patches
ansible/               node provisioning for the old cluster
terraform/             Cloudflare R2 buckets and tunnel
docs/                  reference docs for how things are, not how they will change
plans/                 design docs, written before the work
.taskfiles/            task definitions
scripts/               validation and helper scripts
```

## AI

I leverage coding agents heavily to help build and maintain this project since my time is very limited. I do try to review every line of code though.

[AGENTS.md](./AGENTS.md) covers AI best practices: the app layout, secrets handling, validation, and the failure modes this cluster has hit.

## Credits

I am so incredibly thankful to many contributors of the home automation / self-hosting / OSS community. You have my eternal gratitude.

This project started from [onedr0p/cluster-template](https://github.com/onedr0p/cluster-template) and has since diverged. The manifests here are edited directly rather than generated.
