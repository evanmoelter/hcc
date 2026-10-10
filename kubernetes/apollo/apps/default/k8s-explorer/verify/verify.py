import json
import os
from pathlib import Path
import subprocess
import sys
import time

from k8s_explorer.config import Settings
from k8s_explorer.runtime import sync_catalogue
from k8s_explorer.service import Explorer


def write(path, data):
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def main():
    explorer = Explorer(Settings())
    output = Path("/data/deployment-check-v1")
    output.mkdir()
    deadline = time.monotonic() + 7200
    previous = None
    while True:
        snapshots = explorer.store.snapshots(limit=100)["items"]
        ready = sum(explorer.provider.cache_key in item["semantic_providers"] for item in snapshots)
        state = {"selected_repositories": len(snapshots), "ready_repositories": ready}
        if state != previous:
            print(json.dumps(state), flush=True)
            previous = state
        if ready == len(snapshots) == 20:
            break
        if time.monotonic() > deadline:
            raise TimeoutError("Initial catalogue ingestion did not become ready")
        time.sleep(15)
    write(output / "initial-snapshots.json", snapshots)
    before = {item["repo_id"]: item["commit"] for item in snapshots}
    result = sync_catalogue(explorer)
    write(output / "repeat-sync.json", result)
    unchanged = [item for item in result["items"] if item.get("commit") == before.get(item["repo_id"])]
    cached = bool(unchanged) and all(item.get("semantic", {}).get("embedded") == 0 for item in unchanged)
    summary = {"failed": result["failed"], "repositories": len(result["items"]),
               "unchanged_repositories": len(unchanged), "unchanged_embeddings_reused": cached,
               "new_embeddings": sum(item.get("semantic", {}).get("embedded", 0) for item in result["items"]),
               "usage": explorer.provider.usage_stats}
    write(output / "cache-summary.json", summary)
    print(json.dumps(summary), flush=True)
    if result["failed"] or len(result["items"]) != 20 or not cached:
        raise ValueError("Repeat sync did not verify cache reuse for the catalogue")
    with (output / "smoke.json").open("w") as stream:
        subprocess.run(["k8s-explorer", "check-serving", "--min-ready-repositories", "20"],
                       stdout=stream, check=True)
    report = json.loads((output / "smoke.json").read_text())
    print(json.dumps(report), flush=True)
    write(output / "completed.json", {"status": "passed", "smoke": report, "cache": summary})


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
