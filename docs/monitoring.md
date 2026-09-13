# Apollo monitoring

Apollo's bootstrap metrics configuration lives in `kubernetes/apollo/apps/monitoring/kube-prometheus-stack/`.
Its Flux Kustomization waits for Spegel and uses `wait: true`. The HelmRelease installs Prometheus Operator,
Prometheus, Alertmanager, kube-state-metrics, node-exporter, and the chart's Kubernetes recording and alerting rules.
Deployment and all 32 active scrape targets were verified healthy on 2026-09-09.

Prometheus keeps up to two days or 3 GB of retained blocks in a 5 GiB disk-backed `emptyDir`, with room for the WAL
and compaction. Alertmanager uses a 256 MiB `emptyDir`. Pod replacement loses metrics history and alert silences.
This lets metrics start before Longhorn. Grafana is disabled, and Alertmanager has no notification receiver configured.

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

## Cluster dashboard

kube-ops-view provides Apollo's node and pod overview at `https://kube-ops-view-apollo.${SECRET_DOMAIN}` on the LAN
and as `kube-ops-view-apollo` in Tailscale. These cluster-specific names let the old cluster keep its
existing dashboard during migration. The HTTPRoute attaches only to `envoy-internal`, with UniFi DNS and the shared
wildcard certificate. LAN access has no application login; tailnet access follows the existing Tailscale policy.
The route disables request timeouts for kube-ops-view's server-sent event stream.

One replica keeps its state in memory and needs neither Redis nor a PVC. Its service account can only list nodes,
pods, and their resource metrics. The Tailscale Ingress reconciles separately, after the dashboard and ProxyClass.
The upstream image is pinned because home-operations does not currently publish kube-ops-view.

Metrics-server supplies the `metrics.k8s.io` API used by kube-ops-view, `kubectl top`, and resource-based HPAs;
Prometheus serves a separate purpose. Metrics-server waits for the Prometheus stack's ServiceMonitor CRD, and
kube-ops-view waits for metrics-server and the internal Gateway. Both workloads use non-root UID/GID 568,
read-only root filesystems, and writable `/tmp` volumes.

Metrics-server skips kubelet serving-certificate verification, matching the existing Prometheus kubelet TLS exception.
Its aggregated API also uses the chart's default self-signed certificate with APIService verification disabled.
Removing these exceptions requires separate certificate work; no kubelet CSR approver is introduced here.
The metrics-server configuration follows
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/kube-system/metrics-server/metrics-server.yaml)
and [szinn](https://github.com/szinn/k8s-homelab/tree/main/kubernetes/main/apps/kube-system/metrics-server/app).

Deployment and browser verification remain pending. After Flux deploys the changes:

```sh
kubectl --context apollo get apiservice v1beta1.metrics.k8s.io
kubectl --context apollo top nodes
kubectl --context apollo top pods -A
kubectl --context apollo -n monitoring get helmrelease kube-ops-view
kubectl --context apollo -n monitoring get httproute kube-ops-view
kubectl --context apollo -n monitoring get ingress kube-ops-view-tailscale
```

Confirm the metrics API is Available and all three nodes report usage. Open the dashboard over both LAN HTTPS and
the Ingress's assigned tailnet HTTPS hostname, verify that Apollo's nodes and pods appear with CPU and memory usage,
and leave it open to confirm updates continue. The `/health` probe checks the web process, not Kubernetes API access.

The Talos etcd discovery and cross-namespace monitor settings follow
[onedr0p's stack](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/o11y/kube-prometheus-stack/app/helmrelease.yaml)
and [joryirving's stack](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/observability/kube-prometheus-stack/helmrelease.yaml).
Chart values and generated security settings were checked against kube-prometheus-stack 90.0.0 and Prometheus Operator v0.93.1.
