# In-cluster explorer evaluation

## Overview

Apollo runs corpus preparation and provider evaluation for 20 public repositories. Frozen inputs,
reports, and run metadata survive Job completion on a dedicated artifact PVC. The existing HCC PR
owns this temporary installation; the application and evaluation algorithms remain upstream.

## Design

The storage lifecycle creates a disposable model cache and a retained artifact volume. An app
lifecycle runs one TEI model on hcc8 and a read-only artifact server. Preparation and evaluation
Jobs also use hcc8 so the RWO artifact volume has one node attachment. A preparation lifecycle
depends on storage, and explicit evaluation lifecycles depend on successful preparation and the
serving app. Credential delivery has its own lifecycle, so missing paid-provider keys cannot
prevent corpus preparation or CPU evaluation.

Each Job owns an ephemeral pgvector database as a native sidecar. PostgreSQL listens only on
loopback inside that pod and uses local trust authentication. The runner creates the vector
extension, uses the upstream CLI, and writes source-bound artifacts to persistent storage.
Database files use an emptyDir and disappear with the pod. No production database is involved.

The published application image is pinned to its source commit and digest. Preparation downloads
the upstream tokenizer-check helper and calibration starter from that same commit, checks their
SHA-256 hashes, and retains them with the frozen corpus. Repository ingestion does not execute
code from the indexed repositories. All 20 catalogue entries must successfully export before
preparation completes. Unchanged pilot judgments may be rebound as candidates; changed evidence
requires review. Evaluation requires explicitly approved corpus and judgment hashes.

Jobs have fixed run identities, no automatic retries or TTL deletion, and no forced Flux
replacement. A durable directory created exclusively before each attempt prevents duplicate
execution after pod or Job recreation. Failed attempts remain available for inspection; reruns
need a new attempt ID and Job name. Evaluation Jobs start suspended. Paid runs additionally
require an approved budget record and only the relevant provider credential. These controls
prevent automatic repeated spending but do not implement a provider-side dollar cap.

CPU models run sequentially through GitOps changes to the TEI model and the corresponding Job's
suspension flag. The tokenizer preflight verifies the actual serving revision before any
embedding calls. Reports retain provider configuration, artifact hashes, application identity,
timestamps, and TEI info/metrics snapshots. Prometheus supplies resource telemetry separately.

## Security and retention

Pods have no Kubernetes credentials. Services have no ingress route. NetworkPolicy permits
the evaluation runner and monitoring to reach TEI; the artifact server is reached through
authorized port-forward. Provider keys arrive through ESO and never enter artifact metadata.
The read-only artifact server has no credential mounts and cannot modify results.

Model cache data is reproducible and prunable. The artifact PVC disables Flux pruning and has
three Longhorn replicas; it has no offsite backup. Export and verify the artifacts before
retirement. Cleanup removes workloads first; artifact deletion requires an explicit later
operator decision.

## Decisions and execution

- Operator, 2026-10-07: use 20 repositories and include paid providers.
- Operator, 2026-10-07: run the complete evaluation in Apollo, superseding the local harness choice.
- Codex: use native pgvector sidecars and the existing published application image.
- Pending: operator-managed credential item and spending amount, frozen corpus and judgment review,
  deployment verification, tokenizer checks, actual evaluation results, and artifact export.

The existing upstream embedding-evaluation design remains the authority for measurement and
judgment methodology. This plan covers cluster execution only.

## Validation record

2026-10-07: Apollo schemas and all 57 repository tests pass, including eight evaluation lifecycle
and authorization checks. Full Flux rendering passes with the credential lifecycle intentionally
suspended. A disposable local container test initializes the published runner's schema against
the pinned pgvector image with non-root users, a read-only root filesystem, dropped capabilities,
and loopback-only TCP. Both upstream helper downloads match their pinned checksums. The test uses
the local ARM64 image variants; Apollo's AMD64 execution and native sidecar lifecycle remain unverified.

The live Apollo client is rejected pending operator kubeconfig renewal, so today's capacity and
deployment checks remain unverified. No embedding provider calls have been made.
