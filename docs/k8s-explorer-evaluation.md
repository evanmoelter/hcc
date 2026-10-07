# Explorer embedding evaluations

Apollo runs the temporary 20-repository evaluation for
[k8s-at-home-explorer](https://github.com/evanmoelter/k8s-at-home-explorer).
Corpus preparation, disposable databases, and provider comparisons run as Jobs on hcc8.
One TEI server hosts Qwen3 and then BGE-M3 on the same hardware. Hosted-provider Jobs call
OpenAI and Voyage directly. The permanent explorer service remains a separate installation.

The upstream [evaluation guide](https://github.com/evanmoelter/k8s-at-home-explorer/blob/f0d54ffdfb748a145a51f6187281bd2c3148cf98/docs/embedding-evaluation.md)
owns the benchmark and judgment methodology. Its
[serving guide](https://github.com/evanmoelter/k8s-at-home-explorer/blob/f0d54ffdfb748a145a51f6187281bd2c3148cf98/docs/embedding-serving.md)
owns model revisions, token limits, and measurements. The
[execution plan](../plans/20261007-explorer-evaluation.md) records this installation's decisions and remaining verification.

## Lifecycles and storage

The storage Kustomization waits for Longhorn and creates a prunable model cache and a retained
artifact PVC. The app lifecycle runs TEI and a read-only artifact server. Preparation waits for
storage; provider runs wait for preparation and the app. Paid runs also wait for the credential
lifecycle, which stays suspended until the operator confirms the 1Password item.

All artifact consumers use hcc8 so the RWO volume has one node attachment. Each Job starts its
own pgvector native sidecar with an emptyDir database. PostgreSQL listens only on pod loopback
and trusts connections from the runner in that pod. It uses its image's UID 999; the runner uses
568. The database stops with the Job and its files disappear when the pod is deleted. Neither
household databases nor CNPG backups participate in this disposable experiment.

The artifact PVC disables Flux pruning. Its three Longhorn replicas provide local redundancy,
not an offsite backup. Export and verify the artifacts before retiring it. The model cache
contains only public downloadable weights and can be deleted after use.

## Prepare and review the corpus

Merging the deployment starts `k8s-explorer-eval-prepare-v1`. Its checked-in catalogue selects
20 repositories. It fetches each selected branch once, records the actual commits, and exports
source-verified chunks. Any failed repository or missing export entry blocks completion.
No embedding endpoint or hosted key is used during preparation.

Preparation also downloads the tokenizer helper and pilot judgment starter from the pinned
application commit and verifies their SHA-256 hashes. The published image already contains the
remaining CLI, so no image build is required for this installation. The downloaded helper only
runs after its checksum is checked again. Indexed repository code is never executed.

Preparation writes under `/artifacts/corpora/expanded-20261007-v1/`:

- `corpus.json`, `repositories.yaml`, `sync.json`, and retained source;
- `prepared.json`, with corpus identity, SHA-256, repository and chunk counts;
- the pinned tokenizer helper and pilot starter;
- `candidate-judgments.json` only if every judged pilot passage rebinds unchanged.

A failed rebind does not discard a valid corpus export. Review changed evidence and supply new
judgments. The pilot's sparse 50-question calibration set is not a final holdout for 20 repositories.
A successful rebind is only a candidate; it does not automatically authorize evaluation.

Download artifacts through the read-only service:

```sh
kubectl --context apollo -n default port-forward --address 127.0.0.1 service/k8s-explorer-eval-artifacts 8089:8088
```

Browse `http://127.0.0.1:8089/` or download individual files with `curl --fail --output FILE URL`.
There is no public route. NetworkPolicy denies direct access to the artifact service; authorized
Kubernetes port-forward reaches it through the API server. The server has no provider credentials.

## Approve and run a comparison

All five provider Jobs start suspended. Review the frozen inputs, then set their exact byte
SHA-256 hashes and selected provider IDs in
[`jobs/base/approval.json`](../kubernetes/apollo/apps/default/k8s-explorer-eval/jobs/base/approval.json).
The initial empty hashes and provider list deliberately block execution.

To use independently reviewed judgments, add `reviewed-judgments.json` to that directory and
to its ConfigMap generator's `files` list. Otherwise the runner uses the preparation candidate.
Record the hash of whichever file will actually run. All providers must use identical corpus
and judgment artifacts. Provider endpoint/model settings are in `jobs/base/providers.yaml`.

For paid providers, create the proposed `k8s-explorer-eval` item in the `hcc-apollo` vault with
`OPENAI_API_KEY` and `VOYAGE_API_KEY` fields, following [Apollo secrets](secrets.md). Confirm the
actual item title before enabling `ks-credentials.yaml`. ESO supplies only the relevant key to
each provider Job. Keys never belong in Git, approval records, or artifact files.

Record the operator-approved `openai_budget_usd`, aggregate `voyage_budget_usd`, and `approved_by`
in the approval file before paid execution. The budget record is an authorization prerequisite,
not a dollar meter: the upstream harness does not enforce spending caps. Configure provider
account controls separately and review reported usage between runs, including both Voyage models.

Enable one provider at a time by adding `spec.suspend: false` to its Job patch in
`runs/<provider>/kustomization.yaml`, then commit and let Flux converge. Start with Qwen3.
For BGE-M3, change the TEI HelmRelease environment to the upstream pinned model revision and
CLS pooling in the same activation change. The tokenizer preflight checks the actual model
identity, special tokens, query instruction, and input lengths before embedding calls.

TEI needs `AUTO_TRUNCATE=true` to boot Qwen with the reduced serving cap. The benchmark adapter
explicitly sends `truncate:false`, so oversized evaluation inputs fail. Do not silently change
chunking for one provider; a changed corpus is a new comparison for every provider.

Each run writes under `/artifacts/runs/<experiment>/<run-id>/`, including the approved judgments,
provider settings, runner source, image identity, hashes, timestamps, token preflight for CPU
models, and hybrid retrieval report. CPU runs also save TEI `/info` and `/metrics` before and after.
`completed.json` distinguishes a completed report from an interrupted attempt.

## Retry and reconciliation behavior

Jobs use no TTL cleanup, `backoffLimit: 0`, and `restartPolicy: Never`. Flux does not force
replacement of immutable Jobs. A persistent attempt directory is created exclusively before
work begins; a recreated pod cannot repeat that identity, including after partial paid calls.
A filesystem lock also prevents concurrent attempts. Enable one Job at a time; a simultaneous
attempt fails rather than waiting while consuming database resources.

ConfigMap names are stable so approval edits do not change an existing Job's immutable pod template.
The runner snapshots run configuration into its artifact directory and checks the copied inputs.
Do not edit a running experiment's configuration. To retry a provider, inspect its partial results
and usage, choose a new `EVAL_RUN_ID` and matching Job `nameSuffix`, and commit the change.
To repeat preparation, use a new experiment ID and preparation Job suffix; never overwrite the
previous frozen corpus. Give each provider a new Job suffix and reference the new experiment.
Failed upstream runs may not emit usage totals; check provider accounting before authorizing a retry.

## Verification and retirement

Check Flux readiness, Job status, and the private services:

```sh
kubectl --context apollo -n flux-system get kustomizations | rg k8s-explorer-eval
kubectl --context apollo -n default get jobs,pods,pvc | rg k8s-explorer-eval
kubectl --context apollo -n default logs job/k8s-explorer-eval-prepare-v1 -c runner
```

Verify hcc8's CPU capabilities, model `/info`, startup behavior, and Prometheus target before
interpreting CPU measurements. Record cold download/startup separately from cached startup.
Use Prometheus for memory working set/RSS, CPU usage and throttling, restarts, OOMs, and competing
node load over each run interval. Export telemetry promptly: Apollo keeps only two days of metrics.
A `kubectl top` sample does not establish peak memory. Missing telemetry remains unmeasured.

Scale only the TEI controller to zero through Git to stop inference while keeping results downloadable.
After exporting artifacts and verifying their hashes, remove run/preparation registrations, then
app and credential registrations, and finally storage registration. The model cache is pruned;
the artifact PVC remains until the operator explicitly authorizes deletion. Remove unused manifests
and this documentation entry when retiring the experiment.
