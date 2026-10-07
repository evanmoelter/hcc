import hashlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SOURCE_COMMIT = "f0d54ffdfb748a145a51f6187281bd2c3148cf98"
UPSTREAM_FILES = {
    "scripts/check-embedding-inputs.py": "a7dc3d753631dbe6476490ef62888d648e9b763f3701f20189defc7f9f5935e0",
    "config/evaluation/pilot-judgments.json": "046abd808ffba3b7dcb90906b7533d4deda56b7bb6976b7789898eec54c6f262",
}
PROVIDERS = {"qwen3-0.6b", "bge-m3", "openai-small", "voyage-code-4", "voyage-4"}
DATABASE_URL = "postgresql://explorer@127.0.0.1:5432/explorer"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def identity(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,79}", value):
        raise ValueError("Invalid experiment or run identity")
    return value


def claim_attempt(root, run_id):
    path = root / identity(run_id)
    path.mkdir(parents=True, exist_ok=False)
    write_json(path / "started.json", {
        "started_at": timestamp(), "source_commit": SOURCE_COMMIT,
        "image": os.environ.get("EVAL_IMAGE"), "node": os.environ.get("NODE_NAME"),
    })
    return path


def command(output, *arguments):
    with output.open("xb") as stream:
        subprocess.run(arguments, stdout=stream, check=True)


def fetch_upstream(directory, source, expected):
    url = f"https://raw.githubusercontent.com/evanmoelter/k8s-at-home-explorer/{SOURCE_COMMIT}/{source}"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Upstream file checksum mismatch")
    path = directory / Path(source).name
    with path.open("xb") as stream:
        stream.write(data)


def initialize_database():
    import psycopg

    with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")


def prepare(artifacts, experiment, config):
    from k8s_explorer.evaluation import FrozenCorpus, _read_artifact, rebind_judgments
    import yaml

    output = claim_attempt(artifacts / "corpora", experiment)
    shutil.copyfile(Path(__file__), output / "runner.py")
    os.environ["EXPLORER_DATABASE_URL"] = DATABASE_URL
    os.environ["EXPLORER_CORPUS_DIR"] = str(output / "source")
    shutil.copyfile(config / "repositories.yaml", output / "repositories.yaml")
    repositories = yaml.safe_load((output / "repositories.yaml").read_text())["repositories"]
    if len(repositories) != 20 or len({repo["name"] for repo in repositories}) != 20:
        raise ValueError("Preparation requires exactly 20 distinct repositories")
    for source, expected in UPSTREAM_FILES.items():
        fetch_upstream(output, source, expected)
    initialize_database()
    command(output / "sync.json", "k8s-explorer", "sync", "--catalogue", str(output / "repositories.yaml"))
    command(output / "export.json", "k8s-explorer", "eval", "export", "--output", str(output / "corpus.json"),
            "--max-bytes", "134217728")
    corpus, corpus_hash = _read_artifact(output / "corpus.json", FrozenCorpus)
    if {repo.name for repo in corpus.repositories} != {repo["name"] for repo in repositories}:
        raise ValueError("Export does not contain the complete selected catalogue")
    candidate = output / "candidate-judgments.json"
    try:
        rebind_judgments(output / "corpus.json", output / "pilot-judgments.json", candidate)
        judgments = {"candidate_sha256": digest(candidate), "review_required": True}
    except ValueError:
        judgments = {"review_required": True, "reason": "Pilot evidence changed; supply reviewed judgments"}
    write_json(output / "prepared.json", {
        "completed_at": timestamp(), "corpus_id": corpus.corpus_id,
        "corpus_sha256": corpus_hash, "repositories": len(corpus.repositories),
        "chunks": sum(len(repo.chunks) for repo in corpus.repositories), "judgments": judgments,
    })


def checked_hash(path, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest(path) != expected:
        raise ValueError("Input does not match an approved SHA-256 hash")


def validate_approval(corpus, judgments, approval, provider):
    checked_hash(corpus, approval.get("corpus_sha256", ""))
    checked_hash(judgments, approval.get("judgments_sha256", ""))
    if provider not in PROVIDERS or provider not in approval.get("providers", []):
        raise ValueError("Provider is not approved for this comparison")
    if provider in {"openai-small", "voyage-code-4", "voyage-4"}:
        paid = approval.get("paid", {})
        account = "openai" if provider == "openai-small" else "voyage"
        amount = paid.get(account + "_budget_usd")
        if type(amount) not in {int, float} or not 0 < amount < 10000 or not paid.get("approved_by"):
            raise ValueError("Paid evaluation requires an explicit account budget and approver")


def snapshot_tei(output, suffix):
    import httpx

    base = "http://k8s-explorer-eval.default.svc.cluster.local:8080"
    with httpx.Client(timeout=30, trust_env=False) as client:
        for endpoint in ("info", "metrics"):
            response = client.get(f"{base}/{endpoint}")
            response.raise_for_status()
            with (output / f"tei-{endpoint}-{suffix}.txt").open("xb") as stream:
                stream.write(response.content)


def evaluate(artifacts, experiment, config):
    from k8s_explorer.evaluation import validate_files

    provider = os.environ["EVAL_PROVIDER"]
    corpus_dir = artifacts / "corpora" / experiment
    if not (corpus_dir / "prepared.json").is_file():
        raise ValueError("Corpus preparation has not completed")
    approval = json.loads((config / "approval.json").read_text())
    judgments = config / "reviewed-judgments.json"
    if not judgments.is_file():
        judgments = corpus_dir / "candidate-judgments.json"
    corpus = corpus_dir / "corpus.json"
    validate_approval(corpus, judgments, approval, provider)
    validate_files(corpus, judgments, config / "providers.yaml")
    output = claim_attempt(artifacts / "runs" / experiment, os.environ["EVAL_RUN_ID"])
    for source, name in ((Path(__file__), "runner.py"), (judgments, "judgments.json"), (config / "providers.yaml", "providers.yaml"),
                         (config / "approval.json", "approval.json")):
        shutil.copyfile(source, output / name)
    validate_approval(corpus, output / "judgments.json", approval, provider)
    validate_files(corpus, output / "judgments.json", output / "providers.yaml")
    write_json(output / "inputs.json", {
        "corpus_sha256": digest(corpus), "judgments_sha256": digest(output / "judgments.json"),
        "providers_sha256": digest(output / "providers.yaml"), "provider": provider,
        "runner_sha256": digest(Path(__file__)), "image": os.environ["EVAL_IMAGE"],
        "node": os.environ.get("NODE_NAME"),
    })
    common = ["--corpus", str(corpus), "--judgments", str(output / "judgments.json"),
              "--providers", str(output / "providers.yaml"), "--provider", provider]
    cpu = provider in {"qwen3-0.6b", "bge-m3"}
    if cpu:
        helper = corpus_dir / "check-embedding-inputs.py"
        checked_hash(helper, UPSTREAM_FILES["scripts/check-embedding-inputs.py"])
        snapshot_tei(output, "before")
        command(output / "token-check.log", sys.executable, str(helper), *common,
                "--output", str(output / "token-preflight.json"))
    initialize_database()
    os.environ["EXPLORER_EVAL_DATABASE_URL"] = DATABASE_URL
    command(output / "summary.json", "k8s-explorer", "eval", "run", "--mode", "hybrid",
            "--confirm-disposable-database", *common, "--output", str(output / "report.json"))
    if cpu:
        snapshot_tei(output, "after")
    validate_approval(corpus, output / "judgments.json", approval, provider)
    write_json(output / "completed.json", {"completed_at": timestamp(), "report_sha256": digest(output / "report.json")})


def main():
    artifacts = Path(os.environ.get("EVAL_ARTIFACTS", "/artifacts"))
    config = Path(os.environ.get("EVAL_CONFIG", "/config"))
    experiment = identity(os.environ["EVAL_EXPERIMENT"])
    with (artifacts / "execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if sys.argv[1:] == ["prepare"]:
            prepare(artifacts, experiment, config)
        elif sys.argv[1:] == ["evaluate"]:
            evaluate(artifacts, experiment, config)
        else:
            raise ValueError("Expected prepare or evaluate")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
