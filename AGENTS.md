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

`kubernetes/apollo/` runs Cilium, Flux, Spegel, Reloader, bootstrap metrics, ESO, 1Password Connect, cert-manager, Longhorn, snapshot-controller, VolSync, Envoy Gateway, Cloudflare and UniFi external-dns, cloudflared, and echo-server; [docs/secrets.md](./docs/secrets.md) describes secret setup, app integration, and opt-in configuration reloads, and [docs/certificates.md](./docs/certificates.md) covers certificate issuance. [docs/storage.md](./docs/storage.md) covers Longhorn disk configuration, CSI snapshots, VolSync, and node registration. [docs/gateway.md](./docs/gateway.md) covers ingress and LAN verification; [docs/dns.md](./docs/dns.md) covers DNS ownership, Terraform tunnel setup, and external testing. [docs/talos-security.md](./docs/talos-security.md) covers Secure Boot, TPM encryption, and node conversion. No household apps have moved yet. New platform components and new apps go there. Changes to an app still served by `kubernetes/main/` land in that tree, and each one is worth weighing against the migration: work that Wave 1 will throw away is usually not worth doing.
