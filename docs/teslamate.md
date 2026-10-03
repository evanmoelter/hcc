# TeslaMate

TeslaMate runs in `default` on Apollo with its own CNPG database. Grafana runs in `monitoring` and
uses that database for the TeslaMate dashboards. Both are available on the LAN; Grafana also keeps
its Tailscale hostname. MQTT remains disabled. There is no public Gateway route for either service.

The app stores its durable state in PostgreSQL. Its filesystem cache is disposable, with `HOME`
and the elevation cache redirected to `/tmp` so the container can run as UID 568 with a read-only
root filesystem. Use a single replica and Recreate strategy: startup applies database migrations,
and two concurrent collectors must not write for the same vehicles.

The original encryption key comes from `hcc-apollo/teslamate`, field `ENCRYPTION_KEY`. Preserve it
when restoring the database or the stored Tesla tokens cannot be decrypted. The destination database
password comes from `hcc-apollo/teslamate-postgres`, field `password`; username and database name
remain readable in git. ESO renders a basic-auth Secret for CNPG and a separate password Secret in
Grafana's namespace. Recovery must reference the same destination basic-auth Secret so the database
and Grafana continue to agree on credentials.

Grafana remains disposable, with its datasource and dashboards provisioned through Helm values.
Dashboards are pinned to the TeslaMate release and should move with its application schema. UI edits
are not durable. Anonymous Editor access on LAN/Tailscale is retained by operator decision during migration.
The [Grafana management decision](monitoring.md#grafana-management-decision) defers operator adoption until
Grafana expands into shared cluster monitoring.

Backups use the shared [Postgres component](../kubernetes/apollo/components/postgres/) with an
Apollo-specific archive. The [cutover record](../plans/20261002-teslamate-migration.md) holds source
import details, the pre-existing recording outage, verification gates, and the separate repair step.
A Ready pod proves the HTTP process is running; verify new vehicle telemetry and a new drive or charge
to establish working collection.

The workload hardening and startup grace draw from
[Billimek's TeslaMate deployment](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/default/teslamate/teslamate.yaml).
The secret-backed TLS datasource follows its
[Grafana integration](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/monitoring/grafana/instance/datasource-teslamate.yaml).
