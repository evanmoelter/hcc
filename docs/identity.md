# Apollo identity

Authentik uses its upstream chart and a dedicated CNPG database in `security`. Server and worker
connect directly to that database with CNPG-generated app credentials and certificate verification.
Redis and a connection pooler are not required. Database readiness gates the app; Mealie and
WebFinger depend on Authentik. Future in-cluster OIDC consumers should declare the same dependency.

The operator confirmed that this instance has no files or separately managed outposts to migrate.
Its durable state lives in PostgreSQL. No media PVC is provisioned, and the read-only filesystem
prevents local uploads from becoming unbacked state. Add persistent media storage before enabling
file uploads. Temporary runtime files use an `emptyDir` at `/tmp`.

The chart's managed-outpost service account is disabled. Server and worker use an unprivileged
ServiceAccount with token automount disabled. Both export metrics to Prometheus and opt into Reloader.
Helm retries failed upgrades without automatically rolling back the application version: Authentik
[does not support downgrades](https://docs.goauthentik.io/install-config/upgrade/).

## Credentials

The `hcc-apollo/authentik` item supplies `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_EMAIL__USERNAME`, and
`AUTHENTIK_EMAIL__PASSWORD` through ESO. Preserve the original secret key during migration;
generating a replacement changes signed data and user identifiers. SMTP configuration remains in Helm
values. The database password comes from `authentik-pg-app`, not the legacy shared database credential.

## Access and proxy trust

Both Gateways serve `sso.${SECRET_DOMAIN}` over HTTPS. The app NetworkPolicy admits HTTP only from
those Gateway pods and metrics only from Prometheus. Authentik trusts the Apollo pod CIDR and loopback;
the ingress policy bounds which pods can supply proxy headers.

Authentik's migration release selects the first X-Forwarded-For address. Envoy can retain a
client-supplied leading address even after detecting the real client, so both app routes replace XFF
with `%DOWNSTREAM_REMOTE_ADDRESS_WITHOUT_PORT%`. They fix the forwarded scheme and canonical host,
and remove alternative forwarding and client-certificate headers. Keep both route filters identical.
Use a comma-separated string for `trusted_proxy_cidrs`; the Go listener does not parse a YAML or JSON list
from the environment variable produced by this chart.

After deployment, verify normal and forged-header requests on both LAN and public paths against
Authentik's recorded client address. Route acceptance and chart rendering do not prove this behavior.
See the [Gateway trust model](gateway.md) and the [Authentik cutover gates](../plans/20260919-authentik-migration.md).

## Tailscale discovery

WebFinger serves only `/.well-known/webfinger` at `${SECRET_DOMAIN}`, through both Gateways. It
advertises the existing Authentik `tailscale` provider. It uses the upstream stateless image with a
pinned digest; its own forwarded-IP logging is disabled. It does not need a Tailscale Ingress.

The tunnel explicitly matches the apex domain as well as wildcard subdomains. The existing certificate
covers both. Removing the apex tunnel rule breaks public Tailscale discovery even when SSO works.

## References

The official chart and per-app CNPG layout draw from
[joryirving](https://github.com/joryirving/home-ops/tree/main/kubernetes/apps/base/security/authentik) and
[Mafyuh](https://github.com/Mafyuh/iac/tree/main/kubernetes/apps/security/authentik).
The other requested community repositories had no current Authentik deployment paths when researched.
Upstream documents [Kubernetes deployment](https://docs.goauthentik.io/install-config/install/kubernetes/)
and [Tailscale integration](https://integrations.goauthentik.io/networking/tailscale/).
Proxy handling is defined in the pinned
[Go middleware](https://github.com/goauthentik/authentik/blob/version/2025.10.3/internal/utils/web/http_forwarded.go)
and [Django middleware](https://github.com/goauthentik/authentik/blob/version/2025.10.3/authentik/root/middleware.py).
Envoy documents [dynamic request headers](https://gateway.envoyproxy.io/docs/tasks/traffic/http-request-headers/).
