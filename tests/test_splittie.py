import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WriteCapTests(unittest.TestCase):
    def test_optional_write_cap_renders_as_a_number(self):
        manifest = ROOT / "kubernetes/apollo/apps/default/splittie/app/externalsecret.yaml"
        secret = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(manifest)]))
        config = secret["spec"]["target"]["template"]["data"]["splittie.yaml"]
        fields = {
            "BUDGET_E": "Example E", "BUDGET_K": "Example K", "BUDGET_J": "Example J",
            "ACCOUNT_E_K": "E split K", "ACCOUNT_K_E": "K split E",
            "ACCOUNT_E_J": "E split J", "ACCOUNT_J_E": "J split E",
            "ACCOUNT_K_J": "K split J", "ACCOUNT_J_K": "J split K",
            "MIRROR_PAYEE_E_K": "K", "MIRROR_PAYEE_K_E": "E",
            "MIRROR_PAYEE_E_J": "J", "MIRROR_PAYEE_J_E": "E",
            "MIRROR_PAYEE_K_J": "J", "MIRROR_PAYEE_J_K": "K",
            "START_DATE": "2026-01-01", "PAYEE_MODE": "memo",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "templates").mkdir()
            (root / "Chart.yaml").write_text("apiVersion: v2\nname: fixture\nversion: 0.1.0\n")
            (root / "templates/config.yaml").write_text(
                '{{- define "config" -}}\n' + config + '\n{{- end -}}\n'
                'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: fixture\ndata:\n'
                '  config: {{ include "config" .Values.fields | quote }}\n'
            )
            for value, expected in ((None, 50), ("", 50), ("200", 200), ("050", 50),
                                    ("0", 0), ("-1", -1), ("abc", 0), ("1.5", 0),
                                    ("200\nsyncs: []", 0)):
                with self.subTest(value=value):
                    selected = fields if value is None else {**fields, "WRITE_CAP": value}
                    rendered = subprocess.check_output(
                        ["helm", "template", "fixture", str(root), "-f", "-"],
                        input=json.dumps({"fields": selected}).encode(),
                    )
                    document = json.loads(subprocess.check_output(["yq", "-o=json", "."], input=rendered))
                    parsed = json.loads(subprocess.check_output(
                        ["yq", "-o=json", "."], input=document["data"]["config"].encode(),
                    ))
                    self.assertIs(type(parsed["writeCap"]), int)
                    self.assertEqual(parsed["writeCap"], expected)
                    self.assertEqual(
                        [[(side["budget"], side["account"]) for side in sync["sides"]] for sync in parsed["syncs"]],
                        [
                            [("e", "E split K"), ("k", "K split E")],
                            [("e", "E split J"), ("j", "J split E")],
                            [("k", "K split J"), ("j", "J split K")],
                        ],
                    )
                    self.assertEqual(
                        [(rule["budgets"], rule["then"][0]["split"][0]["transfer"]) for rule in parsed["rules"]],
                        [(["e"], "E split J"), (["k"], "K split J")],
                    )


class ManualJobTests(unittest.TestCase):
    def test_documented_jobs_override_scheduled_args_and_remove_ownership(self):
        commands = (ROOT / "docs/splittie.md").read_text()
        filters = re.findall(r"jq '([^']+)'", commands)
        self.assertEqual(len(filters), 3)
        original = {
            "metadata": {"name": "manual", "ownerReferences": [{"kind": "CronJob"}]},
            "spec": {
                "ttlSecondsAfterFinished": 604800,
                "template": {"spec": {
                    "imagePullSecrets": [{"name": "splittie-ghcr"}],
                    "containers": [{"name": "app", "args": ["run"], "image": "fixture"}],
                }},
            },
        }
        for expression, expected in zip(filters, (["run", "--dry-run"], ["sweep"], ["run"])):
            with self.subTest(expected=expected):
                result = subprocess.run(
                    ["jq", expression], input=json.dumps(original), text=True,
                    capture_output=True, check=True,
                )
                job = json.loads(result.stdout)
                self.assertNotIn("ownerReferences", job["metadata"])
                args = job["spec"]["template"]["spec"]["containers"][0]["args"]
                if expected == ["sweep"]:
                    self.assertEqual(args, ["sweep", "--sync", "e-j", "--from", "2025-01-01", "--to", "2025-12-31"])
                else:
                    self.assertEqual(args, expected)
                job["spec"]["template"]["spec"]["containers"][0]["args"] = ["run"]
                self.assertEqual(job["spec"], original["spec"])


class LogStartupTests(unittest.TestCase):
    def run_helper(self, states, *, timeout=300, error=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "states.json").write_text(json.dumps(states))
            kubectl = root / "kubectl"
            kubectl.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['SPLITTIE_TEST_DIR'])
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as calls:
    calls.write(json.dumps(args) + '\\n')
if os.environ.get('SPLITTIE_TEST_ERROR') == '1':
    sys.exit(1)
if args[4:6] == ['get', 'job']:
    print('job.batch/fixture')
elif args[4:6] == ['get', 'pods']:
    states = json.loads((root / 'states.json').read_text())
    state = states.pop(0) if len(states) > 1 else states[0]
    (root / 'states.json').write_text(json.dumps(states))
    print(json.dumps({'items': [] if state is None else [{'status': {
        'containerStatuses': [{'name': 'app', 'state': state}]
    }}]}))
elif args[4:] == ['logs', '-f', 'job/fixture', '-c', 'app']:
    print('retained output')
else:
    sys.exit(2)
""")
            kubectl.chmod(0o755)
            if timeout > 1:
                sleeper = root / "sleep"
                sleeper.write_text("#!/bin/sh\nexit 0\n")
                sleeper.chmod(0o755)
            env = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                   "SPLITTIE_TEST_DIR": str(root), "SPLITTIE_TEST_ERROR": str(int(error))}
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/splittie-logs.sh"), "apollo", "fixture", str(timeout)],
                env=env, capture_output=True, text=True, timeout=10,
            )
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            self.assertTrue(all(call[:4] == ["--context", "apollo", "-n", "default"] for call in calls))
            self.assertTrue(all(call[4] in ("get", "logs") for call in calls))
            return result, calls

    def test_waits_through_pod_creation_and_image_pull(self):
        result, calls = self.run_helper([None, {"waiting": {"reason": "ContainerCreating"}}, {"running": {}}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("retained output", result.stdout)
        self.assertEqual(sum(call[4:6] == ["get", "pods"] for call in calls), 3)

    def test_reads_jobs_that_already_succeeded_or_failed(self):
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code):
                result, _ = self.run_helper([{"terminated": {"exitCode": exit_code}}])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("retained output", result.stdout)

    def test_startup_timeout_keeps_the_existing_job(self):
        result, calls = self.run_helper([{"waiting": {"reason": "ImagePullBackOff"}}], timeout=1)
        self.assertEqual(result.returncode, 124)
        self.assertIn("same Job", result.stderr)
        self.assertFalse(any(call[4] == "logs" for call in calls))

    def test_api_failure_stops_without_retrying_or_creating_jobs(self):
        result, calls = self.run_helper([], error=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
