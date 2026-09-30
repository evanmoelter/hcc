# Authentik upgrades on Apollo

Apollo has completed the sequential upgrades from 2025.10.3 through 2026.8.3.
This record preserves the procedure, rollout evidence, and outstanding operator verification.
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
continuous archiving. Follow the [database recovery-point procedure](../docs/databases.md#recovery-points-before-application-upgrades):
a completed base backup plus uninterrupted archived WAL covers subsequent upgrade checkpoints. A new
full backup at every step is optional, primarily to shorten recovery time.

Before new application pods start, record the current application version and a UTC recovery timestamp,
LSN, and WAL segment with this read-only query:

```sh
kubectl --context apollo -n security exec authentik-pg-1 -c postgres -- \
  psql -U postgres -d authentik -Atc 'BEGIN READ ONLY;
    SELECT clock_timestamp(), pg_current_wal_lsn(), pg_walfile_name(pg_current_wal_lsn());
    SELECT last_archived_wal, last_archived_time, failed_count FROM pg_stat_archiver;
    ROLLBACK;'
```

Confirm the checkpoint segment has archived on the same timeline before relying on it for recovery.
Record the base backup and retain it with all required WAL through the rollback window. Keep an
administrator/recovery login available. Merge one release family at a time.

## Verify each step

- Check Flux and Helm readiness, the actual server/worker image, migrations, logs, and restart counts.
- Verify LAN/public login, logout, MFA, Mealie OIDC, WebFinger, and fresh Tailscale login.
- Check SMTP, metrics, trusted-proxy behavior, and any release-specific changes to providers or policies.
- Confirm CNPG readiness and continuous archiving remain healthy. Record operator verification below.

If a step fails, stop advancing and diagnose it. Reverting only the image is not a supported downgrade.
A rollback requires restoring an Apollo base backup and replaying WAL only to the recorded pre-upgrade
`spec.bootstrap.recovery.recoveryTarget.targetTime`, then running the matching application version.
Default recovery replays the latest archived WAL and would reapply the schema upgrade. Follow the
database recovery procedure with operator approval. Agree on any lost writes first;
the old main-cluster database no longer includes changes made since the Apollo cutover.

## Execution record

- Cleanup PR #311 reconciled at `7ea5075`; Authentik was healthy on 2025.10.3 before preparation.
- A local rehearsal on 2026-09-30 bootstrapped a synthetic PostgreSQL 18 database at 2025.10.3,
  then upgraded it through every target in sequence. Migrations, server readiness, and worker
  `ak healthcheck` passed at every step under UID/GID 568, a read-only root filesystem, writable
  `/tmp`, and the corresponding read-only media/data mount. The rehearsal used no production data,
  external integrations, or database TLS; it does not replace the live verification gates.
- Before #312, `authentik-preupgrade-20260930151710` completed at 2026-09-30 15:17:23 UTC.
  Subsequent steps used this base backup and continuous WAL; no additional full backup was required.
- All five upgrade PRs merged on 2026-09-30. Each rollout reached Flux/Helm readiness with server and
  worker Ready and zero restarts. LAN/public login pages returned HTTP 200 and WebFinger returned
  the expected Tailscale issuer. These HTTP checks do not establish authenticated login success.

| PR | Application | Applied revision | Pre-upgrade recovery time (UTC) | Checkpoint WAL segment |
|---|---|---|---|---|
| #312 | 2025.10.4 | `4ac5486` | Base backup completed 15:17:23 | Base backup before first merge |
| #313 | 2025.12.6 | `b4228f2` | 2026-09-30 15:24:22.412583+00 | `000000010000000000000074` |
| #314 | 2026.2.7 | `3bb2588` | 2026-09-30 15:29:29.082740+00 | `000000010000000000000075` |
| #316 | 2026.5.7 | `719a030` | 2026-09-30 15:33:15.269429+00 | `000000010000000000000076` |
| #318 | 2026.8.3 | `4c1c590` | 2026-09-30 15:38:21.753128+00 | `000000010000000000000077` |

The timestamps were recorded while the previous version still served, before new-version pods started.
Each checkpoint WAL segment subsequently archived with zero reported archive failures. This verifies
archival progress, not a production PITR rehearsal; recovery also depends on retained base backups and WAL.

- 2025.12.6: RBAC migrations completed and both workloads moved to the read-only `/data` mount.
- 2026.2.7: migrations completed; a read-only count found no SCIM providers requiring filter review.
- 2026.5.7: 26 migration records applied. The Rust worker passed `ak healthcheck`; server and worker
  metrics were scraped successfully over IPv4 on port 9300 after startup.

- 2026.8.3: 59 migration records applied between 15:39:22 and 15:39:38 UTC. All four SSO/WebFinger
  HTTPRoutes were Accepted with ResolvedRefs at their current generations. Server, worker, and database
  Prometheus targets were healthy. Startup logs contained no warning/error events in the checked window.
- Final proxy checks sent normal and forged forwarding/client-certificate headers over both LAN and
  Cloudflare paths. Correlated Authentik origin logs preserved the independently checked client address,
  canonical SSO host, and HTTPS scheme for all four requests. Redirects stayed relative or on the
  canonical HTTPS host. No authenticated client-certificate flow was exercised. The public-path checks
  used Cloudflare from the LAN workstation; independent off-LAN login remains an operator check.

## Outstanding operator verification

The rollout evidence above does not replace these checks; confirmation has not yet been recorded:

- [ ] Admin login and group/role permissions, including custom policies affected by the release gates.
- [ ] Login/logout and MFA on LAN and off-LAN; fresh Mealie OIDC and Tailscale login.
- [ ] SMTP delivery.

Archive this plan under `plans/done/` after recording the remaining verification.
