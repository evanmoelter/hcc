# Apollo identity

Authentik runs in `security` with a dedicated CNPG database. Server and worker connect directly using
CNPG-generated credentials and certificate verification; the connection limit allows headroom for both.
Database readiness gates Authentik. In-cluster OIDC consumers declare a Flux dependency on Authentik.

Durable state lives in PostgreSQL. Local uploads require persistent media storage; the read-only
filesystem prevents unbacked uploads. A read-only empty mount at `/media/public` satisfies Authentik's
[tenant-file startup migration](https://github.com/goauthentik/authentik/blob/version/2025.10.3/lifecycle/system_migrations/tenant_files.py).
The workloads have no Kubernetes API credentials or managed-outpost
permissions. Helm retries failed upgrades without automatic rollback because Authentik
[does not support downgrades](https://docs.goauthentik.io/install-config/upgrade/).

## Credentials

The `hcc-apollo/authentik` item supplies `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_EMAIL__USERNAME`, and
`AUTHENTIK_EMAIL__PASSWORD` through ESO. Replacing the secret key changes signed data and user identifiers.
SMTP configuration lives in Helm values; database credentials come from `authentik-pg-app`.

## Access and proxy trust

Both Gateways serve `sso.${SECRET_DOMAIN}` over HTTPS. The app NetworkPolicy admits HTTP only from
those Gateway pods and metrics only from Prometheus. Authentik trusts the Apollo pod CIDR and loopback;
the ingress policy bounds which pods can supply proxy headers.

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
[Go middleware](https://github.com/goauthentik/authentik/blob/version/2025.10.3/internal/utils/web/http_forwarded.go)
and [Django middleware](https://github.com/goauthentik/authentik/blob/version/2025.10.3/authentik/root/middleware.py).
Envoy documents [dynamic request headers](https://gateway.envoyproxy.io/docs/tasks/traffic/http-request-headers/).
