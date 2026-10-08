import fcntl
import json
import math
import os
from pathlib import Path
import random
import shutil
import signal
import statistics
import sys
import time

import runner


class TrialDeadline(BaseException):
    pass


def end_trial(signum, frame):
    raise TrialDeadline()


def representative_order(chunks):
    unique = {chunk.content_hash: chunk for chunk in chunks}
    ordered = sorted(unique.values(), key=lambda chunk: (len(chunk.content.encode()), chunk.id))
    strata = [ordered[len(ordered) * i // 4:len(ordered) * (i + 1) // 4] for i in range(4)]
    generator = random.Random(20261007)
    for group in strata:
        generator.shuffle(group)
    return [group[index] for index in range(max(map(len, strata), default=0)) for group in strata if index < len(group)]


def measure(provider, documents, queries, output, duration=600):
    observations = []
    started = time.monotonic()
    outcome = "all_documents_completed"
    pending = None
    previous_handler = signal.signal(signal.SIGALRM, end_trial)
    signal.setitimer(signal.ITIMER_REAL, duration)
    try:
        work = [("query", [query]) for query in queries[::max(1, len(queries) // 10)][:10]]
        work += [("document", documents[index:index + 16]) for index in range(0, len(documents), 16)]
        with (output / "observations.jsonl").open("x") as log:
            for role, batch in work:
                pending = {"role": role, "ids": [item.id for item in batch]}
                request_started = time.monotonic()
                if role == "query":
                    provider.embed_query(batch[0].text)
                else:
                    provider.embed_documents([item.content for item in batch])
                observation = {**pending, "count": len(batch), "seconds": time.monotonic() - request_started}
                if role == "document":
                    observation["bytes"] = sum(len(item.content.encode()) for item in batch)
                observations.append(observation)
                log.write(json.dumps(observation) + "\n")
                log.flush()
                pending = None
    except TrialDeadline:
        outcome = "time_budget_reached"
    except Exception as error:
        outcome = "request_failed"
        pending = {**(pending or {}), "error_type": type(error).__name__}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
    elapsed = time.monotonic() - started
    batches = [item for item in observations if item["role"] == "document"]
    query_times = sorted(item["seconds"] for item in observations if item["role"] == "query")
    document_count = sum(item["count"] for item in batches)
    document_seconds = sum(item["seconds"] for item in batches)
    document_window = elapsed - sum(query_times)
    rate = document_count / document_window if document_count and document_window else None
    return {
        "purpose": "throughput-only; no retrieval-quality scores", "outcome": outcome,
        "budget_seconds": duration, "elapsed_seconds": elapsed, "incomplete_request": pending,
        "unique_corpus_documents": len(documents), "completed_documents": document_count,
        "completed_document_batches": len(batches), "document_seconds": document_seconds,
        "document_window_seconds": document_window,
        "documents_per_second": rate,
        "projected_embedding_hours": len(documents) / rate / 3600 if rate else None,
        "projection_limits": "Incomplete batch time included but outputs excluded; byte-length strata; no database indexing cost",
        "query_count": len(query_times),
        "query_latency_seconds": {"median": statistics.median(query_times),
                                  "p95": query_times[math.ceil(len(query_times) * .95) - 1]} if query_times else None,
        "usage": provider.usage_stats,
    }


def main():
    from k8s_explorer.evaluation import FrozenCorpus, Judgments, Providers, _read_artifact, validate_files

    if os.environ["EVAL_PROVIDER"] != "bge-m3":
        raise ValueError("This trial is authorized only for BGE-M3")
    artifacts = Path(os.environ.get("EVAL_ARTIFACTS", "/artifacts"))
    config = Path(os.environ.get("EVAL_CONFIG", "/config"))
    experiment = runner.identity(os.environ["EVAL_EXPERIMENT"])
    corpus_dir = artifacts / "corpora" / experiment
    corpus_path = corpus_dir / "corpus.json"
    judgments_path = config / "reviewed-judgments.json"
    with (artifacts / "execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        approval = json.loads((config / "approval.json").read_text())
        runner.validate_approval(corpus_path, judgments_path, approval, "bge-m3")
        validate_files(corpus_path, judgments_path, config / "providers.yaml")
        output = runner.claim_attempt(artifacts / "runs" / experiment, os.environ["EVAL_RUN_ID"])
        for source, name in ((Path(__file__), "smoke.py"), (Path(runner.__file__), "runner.py"),
                             (judgments_path, "judgments.json"), (config / "approval.json", "approval.json"),
                             (config / "providers.yaml", "providers.yaml")):
            shutil.copyfile(source, output / name)
        runner.validate_approval(corpus_path, output / "judgments.json", approval, "bge-m3")
        helper = corpus_dir / "check-embedding-inputs.py"
        runner.checked_hash(helper, runner.UPSTREAM_FILES["scripts/check-embedding-inputs.py"])
        runner.snapshot_tei(output, "before")
        runner.command(output / "token-check.log", sys.executable, str(helper),
                       "--corpus", str(corpus_path), "--judgments", str(output / "judgments.json"),
                       "--providers", str(output / "providers.yaml"), "--provider", "bge-m3",
                       "--output", str(output / "token-preflight.json"))
        corpus, corpus_hash = _read_artifact(corpus_path, FrozenCorpus)
        judgments, judgments_hash = _read_artifact(output / "judgments.json", Judgments)
        configurations, providers_hash = _read_artifact(output / "providers.yaml", Providers, yaml_file=True)
        provider = next(item for item in configurations.providers if item.id == "bge-m3").provider()
        documents = representative_order([chunk for repo in corpus.repositories for chunk in repo.chunks])
        runner.write_json(output / "inputs.json", {
            "corpus_sha256": corpus_hash, "judgments_sha256": judgments_hash, "providers_sha256": providers_hash,
            "smoke_sha256": runner.digest(Path(__file__)), "seed": 20261007, "batch_size": 16,
            "selection": "Unique content; shuffle within UTF-8 byte-length quartiles and interleave quartiles",
            "document_ids_in_order": [chunk.id for chunk in documents],
        })
        report = measure(provider, documents, judgments.queries, output)
        runner.write_json(output / "report.json", report)
        runner.snapshot_tei(output, "after")
        runner.write_json(output / "completed.json", {
            "completed_at": runner.timestamp(), "report_sha256": runner.digest(output / "report.json"),
        })
        print(json.dumps(report))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
