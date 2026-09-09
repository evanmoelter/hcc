# Apollo monitoring

Apollo's bootstrap metrics configuration lives in `kubernetes/apollo/apps/monitoring/kube-prometheus-stack/`.
Its Flux Kustomization waits for Spegel and uses `wait: true`. The HelmRelease installs Prometheus Operator,
Prometheus, Alertmanager, kube-state-metrics, node-exporter, and the chart's Kubernetes recording and alerting rules.
Deployment and scrape-target health must be checked after merge.

Prometheus keeps up to two days or 3 GB of retained blocks in a 5 GiB disk-backed `emptyDir`, with room for the WAL
and compaction. Alertmanager uses a 256 MiB `emptyDir`. Pod replacement loses metrics history and alert silences.
This lets metrics start before Longhorn. Grafana is disabled, and Alertmanager has no notification receiver configured.

The chart discovers API server, kubelet/cAdvisor, CoreDNS, controller-manager, scheduler, and etcd metrics.
Talos runs etcd outside Kubernetes, so its Service selects API-server pods to discover control-plane node addresses
on port 2381. The Talos machine configuration already exposes that port and the controller-manager and scheduler
metrics endpoints. Kube-proxy scraping is disabled because Cilium replaces it. The chart's TLS-verification exceptions
for kubelet, controller-manager, and scheduler remain in place for their serving certificates.

Prometheus discovers monitors and rules across namespaces and adds `cluster: apollo` to external labels.
Individual applications still need their own ServiceMonitor or PodMonitor. The monitoring namespace permits privileged
pod admission because node-exporter uses host networking, PID access, and read-only host mounts. Containers run as
UID/GID 568 with privilege escalation disabled and all capabilities dropped.

Services are ClusterIP-only. Once Flux has deployed the stack, access each UI with a separate local port-forward:

```sh
kubectl --context apollo -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
kubectl --context apollo -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093
```

Open `http://localhost:9090/targets` to verify scraping and `http://localhost:9093` for alerts. Confirm all expected
nodes appear and each enabled control-plane target is up before treating bootstrap metrics as operational.

After Longhorn lands, move Prometheus and Alertmanager to PVCs and revisit retention. Add Grafana, authenticated
Gateway routes, and notification credentials when storage, ingress, and ESO are ready. Metrics-server remains a
separate platform task; kube-prometheus-stack does not provide the API used by `kubectl top` or resource-based HPAs.

The Talos etcd discovery and cross-namespace monitor settings follow
[onedr0p's stack](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/o11y/kube-prometheus-stack/app/helmrelease.yaml)
and [joryirving's stack](https://github.com/joryirving/home-ops/blob/main/kubernetes/apps/base/observability/kube-prometheus-stack/helmrelease.yaml).
Chart values and generated security settings were checked against kube-prometheus-stack 90.0.0 and Prometheus Operator v0.93.1.
