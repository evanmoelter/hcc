# Apollo monitoring

Apollo's bootstrap metrics configuration lives in `kubernetes/apollo/apps/monitoring/kube-prometheus-stack/`.
Its Flux Kustomization waits for Spegel and uses `wait: true`. The HelmRelease installs Prometheus Operator,
Prometheus, Alertmanager, kube-state-metrics, node-exporter, and the chart's Kubernetes recording and alerting rules.
Deployment and all 32 active scrape targets were verified healthy on 2026-09-09.

Prometheus keeps up to two days or 3 GB of retained blocks in a 5 GiB disk-backed `emptyDir`, with room for the WAL
and compaction. Alertmanager uses a 256 MiB `emptyDir`. Pod replacement loses metrics history and alert silences.
This lets metrics start before Longhorn. Grafana is disabled, and Alertmanager has no notification receiver configured.
Public-path notifications come directly from Gatus through Pushover; Kubernetes alerts remain visible only in Alertmanager.

The chart discovers API server, kubelet/cAdvisor, CoreDNS, controller-manager, scheduler, and etcd metrics.
Talos runs etcd outside Kubernetes, so its Service selects API-server pods to discover control-plane node addresses
on port 2381. The Talos machine configuration already exposes that port and the controller-manager and scheduler
metrics endpoints. Kube-proxy scraping is disabled because Cilium replaces it. The chart's TLS-verification exceptions
for kubelet, controller-manager, and scheduler remain in place for their serving certificates.

Prometheus discovers monitors and rules across namespaces and adds `cluster: apollo` to external labels.
Individual applications still need their own ServiceMonitor or PodMonitor. Cilium/Hubble and Spegel are not yet scraped;
enabling their metrics where needed and adding monitors remains follow-up work. The monitoring namespace permits privileged
pod admission because node-exporter uses host networking, PID access, and read-only host mounts. Containers run as
UID/GID 568 with privilege escalation disabled and all capabilities dropped.

Prometheus and Alertmanager Services are ClusterIP-only. Access each UI with a separate local port-forward:

```sh
kubectl --context apollo -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
kubectl --context apollo -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093
```

Open `http://localhost:9090/targets` to verify scraping and `http://localhost:9093` for alerts. Confirm all expected
nodes appear and each enabled control-plane target is up before treating bootstrap metrics as operational.

After Longhorn lands, move Prometheus and Alertmanager to PVCs and revisit retention. Add Grafana, authenticated
Gateway routes, and notification credentials when storage, ingress, and ESO are ready.

The Talos etcd discovery and cross-namespace monitor settings follow
[onedr0p's stack](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/o11y/kube-prometheus-stack/app/helmrelease.yaml)
and [joryirving's stack](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/observability/kube-prometheus-stack/helmrelease.yaml).
Chart values and generated security settings were checked against kube-prometheus-stack 90.0.0 and Prometheus Operator v0.93.1.

## Public-path monitoring

Gatus checks `https://echo-apollo.${SECRET_DOMAIN}/` once a minute. Its endpoint-specific resolver uses
Cloudflare DNS over TCP at `1.1.1.1:53`, bypassing UniFi's internal answer. Successful checks require valid
TLS, HTTP 200 without redirects, and the expected echo hostname in the JSON response. This exercises public
DNS, Cloudflare, the tunnel, the external Gateway, and echo together; it does not identify which hop failed.
The pod retains cluster DNS for ordinary lookups, including outbound Pushover requests.

Three consecutive failures trigger a normal-priority Pushover notification. Two consecutive successes
trigger a recovery notification, with reminders no more often than hourly while the failure continues.
Gatus sends directly to Pushover, so these notifications do not depend on Alertmanager routing.

One replica uses memory storage and a Recreate deployment strategy. Restarts discard check history and
alert state, briefly interrupt monitoring, and can produce a new outage notification for an ongoing failure.
Prometheus scrapes Gatus separately. There is no public dashboard; use a local port-forward:

```sh
kubectl --context apollo -n monitoring port-forward svc/gatus 8080:8080
```

Open `http://localhost:8080` for results or `/metrics` for Prometheus output.
Gatus depends on ESO and the monitoring stack, but not on the readiness of the tunnel or echo it monitors.
An unhealthy target must not prevent the monitor from being deployed.

### Pushover setup

Install the Pushover client and register the receiving device. Create an application named `Apollo` at
[Pushover applications](https://pushover.net/apps), then create this item in the `hcc-apollo` vault:

| 1Password item | Field | Value |
|---|---|---|
| `pushover` | `PUSHOVER_USER_KEY` | Account User Key |
| `pushover` | `PUSHOVER_API_TOKEN` | Apollo application's API token |

ESO creates `monitoring/gatus-secret`. Required `secretKeyRef` entries supply both values to the container;
Reloader restarts it after credential changes. Unbraced `$PUSHOVER_USER_KEY` and `$PUSHOVER_API_TOKEN` in
the ConfigMap are expanded by Gatus at startup, leaving Flux to substitute only the cluster variables.

### Deployment and alert-delivery gate

The gate passed across two operator-run tunnel outages on 2026-09-18 UTC. Gatus deployed at revision
`2baf6788`, its ExternalSecret synced, its Pushover provider loaded, and Prometheus scraped it successfully.
During the first outage, the operator confirmed receipt of both the failure and recovery notifications.
During the second outage, cloudflared had zero replicas and the public check failed with HTTP 530 while
LAN echo returned HTTP 200 with valid TLS at `192.168.21.100`. Gatus logged triggering the second outage
alert; receipt of the second test's notifications was not separately confirmed. After restoration, both
tunnel replicas, Flux readiness, and the public check recovered.

Repeat these checks after changing the probe target or notification credentials:

1. Confirm the `gatus` ExternalSecret, HelmRelease, and Flux Kustomization are Ready. Confirm the startup log
   reports `configuredProviders=[pushover]`. Gatus can remain healthy after rejecting an invalid provider,
   so `/health` and pod readiness alone do not establish alert delivery.
2. Confirm repeated successful endpoint checks and a healthy Gatus target in Prometheus. Confirm the
   deployed endpoint uses the public resolver; the outage check below verifies that LAN reachability
   cannot mask a tunnel failure.
3. With explicit operator approval, temporarily stop both cloudflared replicas while leaving Gatus,
   outbound internet, and echo's LAN route running. Suspend the cloudflared Flux Kustomization and
   HelmRelease before scaling its Deployment to zero. This interrupts every Apollo tunnel route,
   including the Flux webhook. Keep the suspension as short as the test permits.
4. Verify the public check fails while LAN echo still works, and confirm the outage notification actually
   arrives on the operator's device after three failed checks. A provider success log alone is insufficient.
5. Restore two cloudflared replicas, resume its HelmRelease and Kustomization, and confirm both are Ready.
   Always restore them even if notification delivery fails. After two successful checks, confirm receipt
   of the recovery notification and verify public echo, tunnel metrics, and Gateway metrics recover.
6. Record the test date and results here, then complete the public-path monitoring gate in the migration plan.

Whole-cluster, Gatus-process, and home-internet outage notification coverage is deferred by operator decision.
An independently hosted uptime check or heartbeat receiver is follow-up work: in-cluster Gatus cannot send
an alert when Apollo or its outbound internet is unavailable. Before removing public echo at the end of the
migration, move this check to a retained public endpoint and repeat the alert-delivery gate.

The explicit public resolver follows
[szinn's Gatus configuration](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/apps/observability/gatus/app/resources/config.yaml).
Pushover delivery is also used by
[onedr0p's monitoring stack](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/o11y/kube-prometheus-stack/app/alertmanagerconfig.yaml).
Provider settings and response conditions follow the
[Gatus documentation](https://github.com/TwiN/gatus/blob/v5.36.0/README.md).

## Cluster dashboard

Open `https://kube-ops-view-apollo.${SECRET_DOMAIN}` on the LAN or use `kube-ops-view-apollo` in Tailscale.
The distinct names keep the old cluster's dashboard available during migration. LAN access has no application
login; tailnet access follows the existing Tailscale policy.

Deployment verification is pending. From the LAN, confirm the dashboard hostname resolves to `192.168.21.100`.
Check `kubectl --context apollo top nodes`, then confirm that both dashboard
URLs show Apollo's nodes and pods with CPU/memory usage and continuing updates. The `/health` probe only checks
the web process, so a Ready pod does not prove that Kubernetes API queries work.

## Flux dashboard

Open `https://flux-ui.${SECRET_DOMAIN}` on the LAN or use `flux-ui` in Tailscale.
The Flux Operator's built-in UI has no application login and stays in its default read-only mode;
reconcile, suspend, resume, and other user actions are disabled. LAN access relies on the trusted network,
and tailnet access follows the existing Tailscale policy. Adding login and actions is a separate decision.
