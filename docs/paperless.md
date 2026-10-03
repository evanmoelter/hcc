# Paperless

Paperless uses the internal Gateway and its existing Tailscale hostname. It has no public HTTPRoute.
Authentik provides OIDC at the unchanged SSO hostname. Preserve the provider ID and registered callback
paths when changing login configuration; existing account links depend on that identity. The migration
temporarily carries the original provider JSON through ESO, including its credentials, until the operator
can separate the readable configuration without changing those links.

The library holds application data, media, and exports. Its VolSync repository and dedicated CNPG archive
are separate from the old cluster's backups. The shared consume claim is a staging directory for scanner
uploads; it has no backup. Dragonfly's in-memory replicas hold pending jobs, not durable document state.
Drain uploads and queued work before moving either staging storage or the broker. The
[cutover record](../plans/done/20260930-paperless-migration.md) preserves migration evidence and outstanding verification.

The bound library PVC retains its original `dataSourceRef` after the temporary restore resources are
removed. Preserve that immutable field and the existing PVC/PV identity. A future library recovery
needs a new restore lifecycle using Apollo's repository, following the
[VolSync recovery procedure](../kubernetes/apollo/components/volsync/README.md). PostgreSQL's shared
component supplies recovery from Paperless's own Apollo archive.

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
