# Paperless

Paperless uses the internal Gateway and its existing Tailscale hostname. It has no public HTTPRoute.
Authentik provides OIDC at the unchanged SSO hostname. Preserve the provider ID and registered callback
paths when changing login configuration; existing account links depend on that identity. The migration
temporarily carries the original provider JSON through ESO, including its credentials, until the operator
can separate the readable configuration without changing those links.

The library holds application data, media, and exports. Its VolSync repository and dedicated CNPG archive
are separate from the old cluster's backups. The shared consume claim is a staging directory for scanner
uploads; it has a separate hourly VolSync backup retaining seven days of snapshots. Dragonfly's
in-memory replicas hold pending jobs, not durable document state.
Drain uploads and queued work before moving either staging storage or the broker. The
[cutover record](../plans/done/20260930-paperless-migration.md) preserves migration evidence and outstanding verification.

The bound library PVC retains its original `dataSourceRef` after the temporary restore resources are
removed. Preserve that immutable field and the existing PVC/PV identity. A future library recovery
needs a new restore lifecycle using Apollo's repository, following the
[VolSync recovery procedure](../kubernetes/apollo/components/volsync/README.md). PostgreSQL's shared
component supplies recovery from Paperless's own Apollo archive.

Consume backups use `tf-hcc-apollo-volsync/paperless-consume`. The `paperless-consume` item in
the `hcc-apollo` 1Password vault supplies its unique `RESTIC_PASSWORD`; R2 access uses the existing
`volsync-r2` item. The snapshot mover uses an RWO clone of the RWX source, leaving the live scanner
share mounted. SFTP's init container seeds `._volsync` so an empty inbox still establishes a
restore point; Paperless's default `._*` ignore pattern excludes it from ingestion. Backup deployment
depends on storage, independently of SFTP and the monitor. A completely empty volume can skip its
initial backup until the seed or an upload appears. Hourly snapshots protect captured pending uploads, but
cannot guarantee a copy of every file passing through between runs or a complete in-progress upload.

Recover consume into a separate temporary PVC using the [VolSync recovery procedure](../kubernetes/apollo/components/volsync/README.md).
Inspect the restored files and copy only complete, missing scans into the live consume directory.
Replaying an entire old inbox can resubmit documents that were already processed.

An independent Telegraf monitor mounts consume read-only and uses its native `filecount` input to count
non-hidden PDFs under `/consume/receipt` whose modification time is over one hour old. Its `health`
output returns HTTP 503 when that count is nonzero or no fresh count has arrived for two minutes.
Gatus checks that internal endpoint each minute and sends a Pushover alert after ten consecutive
failures. Two healthy checks resolve the alert; ongoing failures send hourly reminders. Pod probes
check the TCP listener so a stuck scan does not restart the monitor.

This is a best-effort scanner alert: it does not cover other formats, hidden files, uploads elsewhere,
or every partially unreadable directory. The consume backup still covers the whole claim. The monitor
has no library or credential mounts. Gatus's in-memory state resets on restart, as described in
[monitoring](monitoring.md).

Paperless runs as UID/GID 1000, matching the upstream image and restored files. The upstream
[user-mapping initialization](https://github.com/paperless-ngx/paperless-ngx/blob/v2.20.15/docker/rootfs/etc/s6-overlay/s6-rc.d/init-modify-user/run)
requires privileges to change that identity. The container otherwise runs with a read-only root filesystem,
no capabilities, and no privilege escalation. Writable runtime mounts accommodate s6; the initialization
step creates the configured export and scanner directories. Runtime OCR-language installation is unavailable
in rootless mode; additional languages require an image that already contains them.

Scanner SFTP keeps the original host keys and account identity. OpenSSH starts as root to create the
account and chroot, then serves sessions as UID/GID 1000. Its filesystem must support account creation;
only the required capabilities are retained. The pod omits `fsGroup` so Kubernetes does not make SSH
private host keys group-readable. Paperless prepares the shared consume claim before SFTP starts.
The [upstream account script](https://github.com/atmoz/sftp/blob/master/files/create-sftp-user) prints
credential-bearing user arguments to stdout, so startup suppresses that stream while retaining SSH
diagnostics on stderr. Keep that suppression during troubleshooting.

The scanner needs legacy SSH algorithms explicitly enabled in the included configuration. Access from
the IoT VLAN is limited to the scanner's reserved address and SFTP port in the
[network rules](networking.md#firewall). Reuse the existing host keys when changing images to preserve
the scanner's host identity check.
