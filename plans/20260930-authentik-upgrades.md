# Authentik upgrades on Apollo

Upgrade the migrated Apollo instance from 2025.10.3 through each supported release family.
The [migration record](20260919-authentik-migration.md) retains the import and cutover evidence.

## Sequence

Upstream requires the latest patch in the current family before advancing to the next family and
[does not support downgrades](https://docs.goauthentik.io/install-config/upgrade/).
Stable application targets checked on 2026-09-30:

| Step | Application | Official chart |
|---|---|---|
| 1 | 2025.10.4 | 2025.10.3 |
| 2 | 2025.12.6 | 2025.12.4 |
| 3 | 2026.2.7 | 2026.2.3 |
| 4 | 2026.5.7 | 2026.5.6 |
| 5 | 2026.8.3 | 2026.8.3 |

Prepare the steps as a PR stack, but merge one step at a time. Charts use the latest published chart
in each family, with the application image explicitly pinned to the latest patch and digest.
Recheck published patches if execution is delayed. Wait for successful migrations, healthy workloads, and operator login checks
before advancing. Match any separately deployed outposts to the server version.

## First step: 2025.10.4

The [patch release](https://docs.goauthentik.io/releases/2025.10/#fixed-in-2025104) includes security,
database connection, and health-check fixes. The upstream comparison adds no database migration files;
the tenant-file startup migration and proxy-header middleware are unchanged.

The official chart index and OCI registry have no 2025.10.4 chart. Retain chart 2025.10.3 and its
digest, and override the server/worker image to 2025.10.4 with its published multi-platform digest.
Keep PostgreSQL 18, verified database TLS, and the read-only `/media/public` mount.

## Later release gates

- [2025.12](https://docs.goauthentik.io/releases/2025.12/): RBAC migrates permissions to roles,
  groups gain multiple parents, and group names must be unique. Review custom expressions using
  `Group.parent` or direct user permissions. A read-only count on Apollo found zero duplicate group
  names on 2026-09-30; recheck if group configuration changes before this step. Storage moves to
  `/data` and public file URLs to `/files`. Replace the old read-only media mount with a read-only
  empty `/data` mount; there are no local files to migrate. Uploads and disk-backed exports still
  require a separate persistence design.
- [2026.2](https://docs.goauthentik.io/releases/2026.2/): review SCIM provider group filters if used;
  filtered providers may be disabled for review. Custom policies/mappings should use `User.groups`
  rather than deprecated `User.ak_groups`.
- [2026.5](https://docs.goauthentik.io/releases/2026.5/): the worker moves to a Rust entrypoint and
  default listeners change to IPv6. Explicitly retain IPv4 HTTP, HTTPS, and metrics listeners for
  Apollo. Verify the chart's worker health check and port 9300 scraping after rollout.
- [2026.8](https://docs.goauthentik.io/releases/2026.8/): forwarded headers require a trusted direct
  proxy. Retain Apollo's trusted CIDRs and both route filters; verify real client IP, scheme, and
  hostname on LAN and public paths. If used, update `hash_password` automation to accept passwords
  through standard input rather than positional arguments.

## Before each merge

Confirm the current Authentik server and worker are Ready, login works, and CNPG reports successful
continuous archiving. With explicit operator approval, create a fresh backup of the Apollo database:

```sh
authentik_backup_name="authentik-preupgrade-$(date -u +%Y%m%d%H%M%S)"
kubectl --context apollo create -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: ${authentik_backup_name}
  namespace: security
spec:
  cluster:
    name: authentik-pg
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
EOF
kubectl --context apollo -n security wait \
  "backups.postgresql.cnpg.io/${authentik_backup_name}" \
  --for=jsonpath='{.status.phase}'=completed --timeout=15m
kubectl --context apollo -n security get \
  "backups.postgresql.cnpg.io/${authentik_backup_name}" \
  -o custom-columns='NAME:.metadata.name,PHASE:.status.phase,FINISHED:.status.stoppedAt,ERROR:.status.error'
```

Record the backup identifier and completion time before merging. Keep an administrator/recovery
login available. Do not merge multiple upgrade PRs together or let a version bump skip a family.

## Verify each step

- Check Flux and Helm readiness, the actual server/worker image, migrations, logs, and restart counts.
- Verify LAN/public login, logout, MFA, Mealie OIDC, WebFinger, and fresh Tailscale login.
- Check SMTP, metrics, trusted-proxy behavior, and any release-specific changes to providers or policies.
- Confirm CNPG readiness and continuous archiving remain healthy. Record operator verification below.

If a step fails, stop advancing and diagnose it. Reverting only the image is not a supported downgrade.
A rollback requires restoring an Apollo backup from before that upgrade with a compatible application
version, following the database recovery procedure and operator approval. Agree on any lost writes first;
the old main-cluster database no longer includes changes made since the Apollo cutover.

## Execution record

- Cleanup PR #311 reconciled at `7ea5075`; Authentik was healthy on 2025.10.3 before preparation.
- [ ] Fresh Apollo backup completed before the 2025.10.4 merge.
- [ ] 2025.10.4 deployed and operator verification passed.
- [ ] 2025.12.6 deployed and operator verification passed.
- [ ] 2026.2.7 deployed and operator verification passed.
- [ ] 2026.5.7 deployed and operator verification passed.
- [ ] 2026.8.3 deployed and operator verification passed.
