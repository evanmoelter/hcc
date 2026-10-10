import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


def verified_download(url, expected):
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected.removeprefix("sha256:"):
        raise ValueError("Upstream artifact checksum mismatch")
    return data


def main():
    metadata = json.loads(Path("/config/upstream.json").read_text())
    checkout = Path("/tmp/tests")
    checkout.mkdir()
    packages = Path("/tmp/test-packages")
    packages.mkdir()
    for name, digest in metadata["files"].items():
        url = f"https://raw.githubusercontent.com/evanmoelter/k8s-at-home-explorer/{metadata['revision']}/{name}"
        (checkout / Path(name).name).write_bytes(verified_download(url, digest))
    for wheel in metadata["wheels"]:
        with zipfile.ZipFile(io.BytesIO(verified_download(wheel["url"], wheel["hash"]))) as archive:
            archive.extractall(packages)
    configuration = checkout / "pytest.ini"
    configuration.write_text("[pytest]\nasyncio_mode = auto\nmarkers = integration: disposable database tests\n")
    environment = {**os.environ, "PYTHONPATH": str(packages)}
    result = subprocess.run([
        sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider",
        "--junitxml=/tmp/results.xml",
        str(checkout / "test_store.py") + "::test_real_embedding_provider_and_cache",
        str(checkout / "test_workflow.py") + "::test_real_model_authenticated_serving_and_repeat_sync_cache",
    ], env=environment, check=False)
    cases = ET.parse("/tmp/results.xml").findall(".//testcase")
    passed = result.returncode == 0 and len(cases) == 2 and all(
        not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases
    )
    print(json.dumps({"status": "passed" if passed else "failed", "tests": len(cases),
                      "source_revision": metadata["revision"], "database": "disposable pod-local PostgreSQL"}))
    if not passed:
        raise RuntimeError("Both real-provider integration tests must pass without skips")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
