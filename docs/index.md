# Documentation index

Use the relevant reference for current configuration, integration instructions, and verification evidence.
[Plans](../plans/) cover proposed changes and migration work; [completed plans](../plans/done/) retain
their execution records.

| Topic | Reference |
|---|---|
| Credentials and configuration reloads | [Secrets](secrets.md): ESO, 1Password setup, application integration, and Reloader. |
| Persistent files and backups | [Storage](storage.md): Longhorn, capacity, snapshots, R2 backup separation, and node registration. [VolSync lifecycle usage](../kubernetes/apollo/components/volsync/README.md) covers PVC creation, restore, backup, and cleanup. |
| PostgreSQL and Redis-compatible services | [Databases](databases.md): Postgres components, initialization and recovery, credentials, backups, and Dragonfly integration. |
| HTTP ingress and proxy trust | [Gateway](gateway.md): LAN and external routing, listener isolation, forwarded headers, and verification. |
| DNS and public tunnel | [DNS](dns.md): split-horizon records, ownership, tunnel setup, and external testing. |
| TLS certificates | [Certificates](certificates.md): issuers, credentials, wildcard issuance, and checks. |
| Tailnet access | [Tailscale](tailscale.md): operator identity, OAuth setup, Ingress security, and verification. |
| Addressing, LoadBalancers, and IoT | [Networking](networking.md): VLANs, IP allocation, firewall rules, Multus, and node eligibility. |
| Metrics, alerts, and dashboards | [Monitoring](monitoring.md): Prometheus, public-path checks, Pushover, and cluster/Flux dashboards. |
| Node boot and disk protection | [Talos security](talos-security.md): Secure Boot, TPM encryption, recovery, and node conversion. |
| Manifest policies | [Linting](linting.md): policy definitions, exceptions, tests, and validation scope. |

[Repository conventions](../AGENTS.md#patterns) and [validation commands](../AGENTS.md#validating-changes)
live in AGENTS.md. The [app-onboarding skill](../.agents/skills/add-apollo-app/SKILL.md) provides the
new-app workflow; [community discovery](../.agents/skills/community-discovery/SKILL.md) provides reusable research.
