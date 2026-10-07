import fcntl
import json
import os
from pathlib import Path
import sys

import runner


def main():
    if sys.argv[1:] != ["evaluate"] or os.environ["EVAL_PROVIDER"] not in {
        "openai-small", "voyage-code-4", "voyage-4",
    }:
        raise ValueError("Expected a hosted evaluation provider")
    artifacts = Path(os.environ.get("EVAL_ARTIFACTS", "/artifacts"))
    config = Path(os.environ.get("EVAL_CONFIG", "/config"))
    experiment = runner.identity(os.environ["EVAL_EXPERIMENT"])
    with (artifacts / "hosted-execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.evaluate(artifacts, experiment, config)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
