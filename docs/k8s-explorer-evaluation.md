# Explorer embedding evaluations

Apollo's temporary `k8s-explorer-eval` release provides a private TEI endpoint for
[k8s-at-home-explorer](https://github.com/evanmoelter/k8s-at-home-explorer).
It serves one CPU model at a time on hcc8 so Qwen3 and BGE-M3 can use the same hardware
and resource settings. The explorer service itself is a separate future installation.

The upstream [serving handoff](https://github.com/evanmoelter/k8s-at-home-explorer/blob/f0d54ffdfb748a145a51f6187281bd2c3148cf98/docs/embedding-serving.md)
defines weight revisions, preprocessing, tokenizer checks, and measurements.
The [evaluation guide](https://github.com/evanmoelter/k8s-at-home-explorer/blob/f0d54ffdfb748a145a51f6187281bd2c3148cf98/docs/embedding-evaluation.md)
owns corpus preparation and the benchmark CLI. Keep serving changes here and harness changes upstream.

## Lifecycle and access

The storage Kustomization waits for Longhorn; the app waits for storage and monitoring.
The cache PVC contains only public, downloadable model weights. It has no VolSync backup
and is intentionally pruned when its storage Kustomization is removed. Never store reports,
corpora, or credentials there. Model changes retain the cache and use a Recreate rollout.

The CPU limit bounds interference with household workloads. Startup probes allow a cold
download and warmup; the Deployment progress deadline and Helm timeout also accommodate it.
The AVX2 setting follows the upstream NUC handoff; confirm the serving node's CPU capabilities
and record its model before interpreting performance.

There is no HTTPRoute, external DNS record, or native TEI API key. The ingress NetworkPolicy
allows only Prometheus pods from `monitoring`. An authorized workstation can use Kubernetes
port-forward, which reaches the pod through the API server. An in-cluster benchmark runner
needs an explicit NetworkPolicy peer before using the Service.

After the GitOps change reaches the cluster, verify readiness:

```sh
kubectl --context apollo -n flux-system get kustomization k8s-explorer-eval-storage k8s-explorer-eval
kubectl --context apollo -n default get helmrelease k8s-explorer-eval
kubectl --context apollo -n default get pods -l app.kubernetes.io/instance=k8s-explorer-eval -o wide
kubectl --context apollo -n default get pvc k8s-explorer-eval-cache
kubectl --context apollo -n default port-forward --address 127.0.0.1 service/k8s-explorer-eval 8081:8080
```

Check `/health` and `/info` at `http://127.0.0.1:8081`. Verify model ID, weight SHA,
float32 precision, pooling, and input limits. Smoke-test one vector and a representative batch;
every vector must have 1,024 finite components and nonzero norm.

TEI needs `AUTO_TRUNCATE=true` to start Qwen with the reduced serving context. Every evaluation
request must explicitly send `truncate:false`; the upstream adapter does this. Run the upstream
`eval:token-check` against every prepared document and query before embedding. Byte size alone
does not establish token fit. A failed check blocks that run; changing chunking requires a new,
shared frozen corpus for all candidates.

## Comparison sequence

The operator selected a 20-repository corpus and a local harness in the explorer repository,
including both CPU models and the hosted OpenAI and Voyage candidates. Prepare and freeze
the expanded corpus there, using `config/evaluation/repositories.yaml`, and review judgments
against its actual source. Use identical frozen corpus and judgment files for all providers.
The existing pilot's 50 questions are sparsely judged calibration data, not a final holdout
for the expanded corpus.

Use the upstream `eval:benchmark` task on the workstation and its disposable Compose
pgvector database. It requires no production database credentials. Select only the active
provider, run the token preflight first, then hybrid retrieval. Save reports and hashes with
the frozen inputs outside Git. The initial Qwen forwarding port matches the upstream provider file.

To switch to BGE-M3, change these three environment values in the
[HelmRelease](../kubernetes/apollo/apps/default/k8s-explorer-eval/app/helmrelease.yaml)
and let Flux deploy the commit:

```yaml
MODEL_ID: BAAI/bge-m3
REVISION: 5617a9f61b028005a4858fdac845db406aefb181
POOLING: cls
```

Stop the old port-forward and forward local port `8082` to Service port `8080` for BGE-M3.
Repeat identity checks, smoke tests, and token preflight with `--provider bge-m3` before its
hybrid run. Keep CPU settings, input artifacts, and measurement procedures identical.
Model-switch commits must keep the serving revision aligned with the provider configuration.

The local harness calls OpenAI `text-embedding-3-small` and Voyage `voyage-code-4` and `voyage-4`
directly. Their non-secret settings live in the explorer's `config/evaluation/providers.yaml`.
The operator supplies `OPENAI_API_KEY` and `VOYAGE_API_KEY` to the local process environment;
this deployment needs no provider credentials or ExternalSecret. Never place keys in provider
YAML, Git, logs, or artifacts. Budget approval and credential setup belong to the evaluation
work in the explorer repository and do not block this model-serving deployment. Confirm the
budget there before paid calls; the harness does not enforce a dollar cap.

## Measurements and cleanup

The ServiceMonitor scrapes TEI every 15 seconds. Verify the target is up, and preserve `/metrics`
before and after each run. Use Prometheus container metrics for memory working set, RSS,
CPU usage, throttling, restarts, and OOMs over the exact interval. Apollo retains metrics for
only two days, so export evidence promptly. Record cold download/startup separately from warm
cache startup, and record competing node load and port-forward overhead with query latency.
Do not infer peak memory from a single `kubectl top` sample.

Archive corpus/judgment/provider hashes, application commit, serving image digest, `/info`,
token preflight, relevance reports, usage, and resource telemetry together. Sparse calibration
scores alone do not select a production provider; pooled candidate review and a reviewed holdout
remain upstream work.

To stop compute while retaining weights, commit `controllers.tei.replicas: 0`. To retire the
experiment, first remove the app registration and wait for Flux to delete the workload, then
remove the storage registration. This deletes the cache PVC and its Longhorn replicas.
Remove the unused manifest directory and this catalog entry as part of retirement.
