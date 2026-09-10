# Home Compute Cluster (hcc)

> [!WARNING]
> **Migration in progress; this README is under construction.** The cluster is moving from ansible-managed k3s to Talos. Apollo's nodes run Talos and this tree is building out its platform components, but no workload has moved yet, so everything described here still runs on the old cluster under `kubernetes/main`. Sections marked as placeholders get filled in as the migration proceeds. Where this README and [plans/20260816-talos-migration.md](./plans/20260816-talos-migration.md) disagree, the plan wins.

Kubernetes cluster(s) running the household's services on bare metal in the basement: home automation, recipes, documents, and car telemetry. Flux reconciles everything from this repository using the guiding principles of GitOps.

## Migration status


|              | `kubernetes/main`              | `kubernetes/apollo` |
| ------------ | ------------------------------ | ------------------- |
| Distribution | k3s on Debian, ansible-managed | Talos               |
| Status       | serving all apps; frozen       | Cilium, Flux, Spegel, bootstrap metrics, ESO, Connect, and cert-manager; no apps yet |
| Fate         | deleted in Wave 2              | the cluster         |


Apps cut over one at a time from verified backups. `kubernetes/main` stays intact for rollback until the last app has moved. [plans/20260816-talos-migration.md](./plans/20260816-talos-migration.md) holds the full design: node topology, storage, networking, and per-app data migration.

[Apollo monitoring](./docs/monitoring.md) describes the bootstrap metrics stack, temporary retention, and local access.
[Apollo secrets](./docs/secrets.md) describes ESO, the dedicated `hcc-apollo` vault, and the operator's Connect credential setup.
[Apollo certificates](./docs/certificates.md) describes cert-manager, Cloudflare credential setup, and the staging issuance test.

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
task kubernetes:resources CLUSTER=main      # gather cluster state for troubleshooting
task talos:render CLUSTER=apollo            # for Talos changes; renders machine configs
task talos:kubeconfig CLUSTER=apollo        # refresh Apollo's admin kubeconfig
kubectx main | kubectx apollo               # switch clusters
k9s                                         # poke around
stern -n default <app>                      # tail logs
```

Every task that reads a cluster tree needs `CLUSTER`, naming a directory under `kubernetes/`. There is no default while two clusters exist. `kubectx` picks the cluster for bare `kubectl`; tasks ignore that and use `CLUSTER`. Apollo's kubeconfig is a short-lived admin certificate, so reissue it when it expires.

> Recovery runbooks: placeholder. Filled in as each one is exercised.



## Bootstrapping

A new cluster is built in two stages. `task talos:apply CLUSTER=apollo` installs Talos on nodes in maintenance mode; `talosctl bootstrap` starts etcd on one of them. The cluster then has no CNI, so nothing schedules.

`task bootstrap:cluster CLUSTER=apollo` closes that gap. It installs Cilium and the Flux operator with helmfile, seeds the age key and cluster variables, and points Flux at this repository. Everything after that reconciles from git.



## Repository layout

```
kubernetes/main/       old cluster manifests: bootstrap/, flux/, apps/, templates/
kubernetes/apollo/     new cluster manifests: bootstrap/, flux/, apps/
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
