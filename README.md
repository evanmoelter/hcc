# Home Compute Cluster (hcc)

> [!WARNING]
> **Migration in progress; this README is under construction.** The cluster is moving from ansible-managed k3s to Talos. Apollo's nodes run Talos and this tree is building out its platform components, but no workload has moved yet, so everything described here still runs on the old cluster under `kubernetes/main`. Sections marked as placeholders get filled in as the migration proceeds. Where this README and [plans/20260816-talos-migration.md](./plans/20260816-talos-migration.md) disagree, the plan wins.

Kubernetes cluster(s) running the household's services on bare metal in the basement: home automation, recipes, documents, and car telemetry. Flux reconciles everything from this repository using the guiding principles of GitOps.

## Migration status


|              | `kubernetes/main`              | `kubernetes/apollo` |
| ------------ | ------------------------------ | ------------------- |
| Distribution | k3s on Debian, ansible-managed | Talos               |
| Status       | serving all apps; frozen       | Cilium, Flux, Spegel, Reloader, bootstrap metrics, ESO, Connect, cert-manager, Longhorn, snapshot-controller, VolSync, Envoy Gateway, DNS, cloudflared, and echo-server; no household apps yet |
