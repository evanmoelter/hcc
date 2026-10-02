# Apollo identity

Authentik runs in `security` with a dedicated CNPG database. Server and worker connect directly using
CNPG-generated credentials and certificate verification; the connection limit allows headroom for both.
Database readiness gates Authentik. In-cluster OIDC consumers declare a Flux dependency on Authentik.
HTTP, HTTPS, and metrics listeners explicitly bind IPv4 because the upstream default changed to IPv6
in the 2026.5 release family; Apollo routes and Prometheus use IPv4 pod addresses.

Configuration and identity state live in PostgreSQL. Uploaded files and disk-backed exports use the
shared `authentik-data` PVC at `/data`. This includes application/source icons, logos, favicons, and flow
backgrounds managed through Customization > Files, plus managed report files. Longhorn
[ReadWriteMany](https://longhorn.io/docs/1.12.1/nodes-and-volumes/volumes/rwx-volumes/) lets server and
worker mount the same files across nodes and during rolling updates. A seed file ensures an empty
installation can establish its first VolSync restore point. VolSync snapshots the claim and reads the temporary backup volume as
ReadWriteOnce; backups use Apollo's R2 repository independently of the database archive.
The workloads have no Kubernetes API credentials or managed-outpost
permissions. Helm retries failed upgrades without automatic rollback because Authentik
[does not support downgrades](https://docs.goauthentik.io/install-config/upgrade/).

## Credentials

The `hcc-apollo/authentik` item supplies `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_EMAIL__USERNAME`, and
`AUTHENTIK_EMAIL__PASSWORD` through ESO. Replacing the secret key changes signed data and user identifiers.
SMTP configuration lives in Helm values; database credentials come from `authentik-pg-app`.
The same 1Password item also needs a unique `RESTIC_PASSWORD` for the media backup repository;
the VolSync ExternalSecret consumes it separately from the application credentials.

## File backup and recovery

On 2026-09-30, an isolated Apollo rehearsal verified UID 568 writes across Talos nodes, an RWX snapshot
cloned as RWO, and an RWO snapshot restored as RWX. All disposable resources were removed.
This verifies CSI access-mode transitions; the first VolSync/R2 backup remains a deployment check.

Before enabling uploads, confirm `authentik-storage`, `authentik`, and `authentik-backup` are Ready,
then check the ReplicationSource's `status.lastSyncTime` and `status.latestMoverStatus` for a successful
run whose logs report a saved restic snapshot. A successful empty sync alone is insufficient. Test a small
upload through the UI and verify it remains available after a later rollout.
The [VolSync lifecycle](../kubernetes/apollo/components/volsync/README.md) describes restoring a replacement
claim through preflight and a new restore ID. Keep ReadWriteMany on the replacement application claim.
Database WAL does not contain uploaded files: recovery needs both the database and the file backup,
with compatible restore points for database references to media.

## Access and proxy trust

Both Gateways serve `sso.${SECRET_DOMAIN}` over HTTPS. The app NetworkPolicy admits HTTP only from
those Gateway pods and metrics only from Prometheus. Authentik trusts the Apollo pod CIDR and loopback;
the ingress policy bounds which pods can supply proxy headers. Forwarded headers are honored only
for connections from trusted proxies.

Both routes replace X-Forwarded-For with Envoy's `%DOWNSTREAM_REMOTE_ADDRESS_WITHOUT_PORT%` to prevent
client-supplied addresses from taking precedence. They fix the forwarded scheme and canonical host and
remove alternative forwarding and client-certificate headers. See the [Gateway trust model](gateway.md).
Use a comma-separated string for `trusted_proxy_cidrs`; the Go listener does not parse YAML or JSON lists.

## Tailscale discovery

WebFinger serves `/.well-known/webfinger` at `${SECRET_DOMAIN}` through both Gateways and advertises
the Authentik `tailscale` provider. Public discovery uses the [apex tunnel route](dns.md#apex-domain-routing).

## References

The official chart and per-app CNPG layout draw from
[joryirving](https://github.com/joryirving/home-ops/tree/main/kubernetes/apps/base/security/authentik) and
[Mafyuh](https://github.com/Mafyuh/iac/tree/main/kubernetes/apps/security/authentik).
Upstream documents [Kubernetes deployment](https://docs.goauthentik.io/install-config/install/kubernetes/)
and [Tailscale integration](https://integrations.goauthentik.io/networking/tailscale/).
Proxy handling is defined in the pinned
[Go middleware](https://github.com/goauthentik/authentik/blob/version/2026.8.3/internal/utils/web/http_forwarded.go)
and [Django middleware](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/root/middleware.py).
Envoy documents [dynamic request headers](https://gateway.envoyproxy.io/docs/tasks/traffic/http-request-headers/).
