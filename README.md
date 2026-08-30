# Home Compute Cluster (hcc)

> [!WARNING]
> **Migration in progress; this README is under construction.** The cluster is moving from ansible-managed k3s to Talos. The new cluster, Apollo, is designed but not yet built, so the workloads described here still run on the old cluster under `kubernetes/main`. Sections marked as placeholders get filled in as the migration proceeds. Where this README and [plans/20260816-talos-migration.md](./plans/20260816-talos-migration.md) disagree, the plan wins.

Kubernetes cluster(s) running the household's services on bare metal in the basement: home automation, recipes, documents, and car telemetry. Flux reconciles everything from this repository using the guiding principles of GitOps.

## Migration status


|              | `kubernetes/main`              | `kubernetes/apollo` |
| ------------ | ------------------------------ | ------------------- |
| Distribution | k3s on Debian, ansible-managed | Talos               |
| Status       | serving all apps; frozen       | not yet created     |
| Fate         | deleted in Wave 2              | the cluster         |


Apps cut over one at a time from verified backups. `kubernetes/main` stays intact for rollback until the last app has moved. [plans/20260816-talos-migration.md](./plans/20260816-talos-migration.md) holds the full design: node topology, storage, networking, and per-app data migration.

## Hardware

> Placeholder. Filled in as nodes are provisioned.



## What runs here

> Placeholder. Filled in as apps are deployed.



## Day-2 operations

Tools are pinned in [mise.toml](./mise.toml) and environment variables in [.envrc](./.envrc). `mise install` and `direnv allow` set up a workstation.

```sh
task                              # list every task
flux get kustomizations -A        # what is reconciling, and what is not
flux get helmreleases -A
task flux:reconcile               # pull changes from git now, rather than waiting
task kubernetes:kubeconform       # validate manifests the way CI does
task kubernetes:resources         # gather cluster state for troubleshooting
k9s                               # poke around
stern -n default <app>            # tail logs
```

> Recovery runbooks: placeholder. Filled in as each one is exercised.



## Bootstrapping

> Placeholder. Filled in as the cluster is built.



## Repository layout

```
kubernetes/main/       old cluster manifests: bootstrap/, flux/, apps/, templates/
ansible/               node provisioning
terraform/             Cloudflare R2 buckets and tunnel
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
