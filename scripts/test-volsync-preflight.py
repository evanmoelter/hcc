import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


source = Path(__file__).resolve().parents[1] / "kubernetes/apollo/components/volsync/preflight/preflight.py"
spec = importlib.util.spec_from_file_location("preflight", source)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class RestorePreflightTest(unittest.TestCase):
    snapshot = {"id": "a" * 64, "hostname": "volsync", "paths": ["/data"]}

    def run_preflight(self, output="[]", error=None):
        result = subprocess.CompletedProcess([], 0, stdout=output)
        with patch.object(preflight.subprocess, "run", return_value=result, side_effect=error) as run:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = preflight.main()
        command = run.call_args.args[0]
        self.assertIn("--no-lock", command)
        self.assertIn("--no-cache", command)
        self.assertIn("snapshots", command)
        return code, stderr.getvalue()

    def test_existing_backup_passes(self):
        self.assertEqual(self.run_preflight(json.dumps([self.snapshot]))[0], 0)

    def test_empty_repository_blocks(self):
        self.assertEqual(self.run_preflight("[]")[0], 1)

    def test_incompatible_snapshots_block(self):
        for change in ({"hostname": "other"}, {"paths": ["/other"]}, {"id": ""}):
            with self.subTest(change=change):
                self.assertEqual(self.run_preflight(json.dumps([self.snapshot | change]))[0], 1)

    def test_missing_repository_and_credentials_block_without_leaking_errors(self):
        for code in (1, 10, 12):
            with self.subTest(code=code):
                error = subprocess.CalledProcessError(code, "restic", stderr="private repository detail")
                result, stderr = self.run_preflight(error=error)
                self.assertEqual(result, 1)
                self.assertNotIn("private repository detail", stderr)

    def test_timeout_blocks(self):
        self.assertEqual(self.run_preflight(error=subprocess.TimeoutExpired("restic", 240))[0], 1)

    def test_malformed_results_block(self):
        for output in ("not json", "null", "{}", '[{"id": null}]', '[{"id": 12}]'):
            with self.subTest(output=output):
                self.assertEqual(self.run_preflight(output)[0], 1)


if __name__ == "__main__":
    unittest.main()
