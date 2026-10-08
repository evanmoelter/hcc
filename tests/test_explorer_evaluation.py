import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import time


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/apollo/apps/default/k8s-explorer-eval"
SPEC = importlib.util.spec_from_file_location("evaluation_runner", APP / "jobs/base/runner.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
HOSTED_SPEC = importlib.util.spec_from_file_location("hosted_runner", APP / "jobs/hosted/hosted-runner.py")
HOSTED = importlib.util.module_from_spec(HOSTED_SPEC)
with mock.patch.dict("sys.modules", {"runner": RUNNER}):
    HOSTED_SPEC.loader.exec_module(HOSTED)
SMOKE_SPEC = importlib.util.spec_from_file_location("smoke_runner", APP / "jobs/smoke/smoke.py")
SMOKE = importlib.util.module_from_spec(SMOKE_SPEC)
with mock.patch.dict("sys.modules", {"runner": RUNNER}):
    SMOKE_SPEC.loader.exec_module(SMOKE)


def render(path):
    built = subprocess.run(["kustomize", "build", str(path)], capture_output=True, text=True, check=True)
    result = subprocess.run(
        ["yq", "eval-all", "-o=json", "-I=0", "[.]", "-"],
        input=built.stdout, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


class EvaluationGuardsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.corpus = self.root / "corpus.json"
        self.judgments = self.root / "judgments.json"
        self.corpus.write_text("frozen corpus")
        self.judgments.write_text("reviewed judgments")
        self.approval = {
            "corpus_sha256": RUNNER.digest(self.corpus),
            "judgments_sha256": RUNNER.digest(self.judgments),
            "providers": ["qwen3-0.6b", "openai-small", "voyage-4"],
        }

    def test_recreated_run_cannot_overwrite_or_repeat_attempt(self):
        attempt = RUNNER.claim_attempt(self.root, "qwen-v1")
        marker = (attempt / "started.json").read_bytes()
        with self.assertRaises(FileExistsError):
            RUNNER.claim_attempt(self.root, "qwen-v1")
        self.assertEqual(marker, (attempt / "started.json").read_bytes())

    def test_path_traversal_is_rejected(self):
        for value in ("../outside", "/outside", "", "foo/bar"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RUNNER.claim_attempt(self.root, value)

    def test_changed_inputs_block_previously_approved_run(self):
        RUNNER.validate_approval(self.corpus, self.judgments, self.approval, "qwen3-0.6b")
        self.corpus.write_text("changed corpus")
        with self.assertRaises(ValueError):
            RUNNER.validate_approval(self.corpus, self.judgments, self.approval, "qwen3-0.6b")

    def test_paid_provider_requires_its_own_account_budget(self):
        with self.assertRaises(ValueError):
            RUNNER.validate_approval(self.corpus, self.judgments, self.approval, "openai-small")
        self.approval["paid"] = {"approved_by": "operator", "openai_budget_usd": 5}
        RUNNER.validate_approval(self.corpus, self.judgments, self.approval, "openai-small")
        with self.assertRaises(ValueError):
            RUNNER.validate_approval(self.corpus, self.judgments, self.approval, "voyage-4")

    def test_unselected_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            RUNNER.validate_approval(self.corpus, self.judgments, self.approval, "bge-m3")


class HostedExecutionTests(unittest.TestCase):
    def test_hosted_work_can_run_while_cpu_lock_is_held(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {
            "EVAL_ARTIFACTS": directory, "EVAL_PROVIDER": "openai-small", "EVAL_EXPERIMENT": "test-v1",
        }), mock.patch("sys.argv", ["hosted-runner.py", "evaluate"]), mock.patch.object(RUNNER, "evaluate") as evaluate:
            with (Path(directory) / "execution.lock").open("a") as lock:
                RUNNER.fcntl.flock(lock, RUNNER.fcntl.LOCK_EX | RUNNER.fcntl.LOCK_NB)
                HOSTED.main()
            evaluate.assert_called_once()

    def test_second_hosted_work_is_rejected_before_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {
            "EVAL_ARTIFACTS": directory, "EVAL_PROVIDER": "voyage-4", "EVAL_EXPERIMENT": "test-v1",
        }), mock.patch("sys.argv", ["hosted-runner.py", "evaluate"]), mock.patch.object(RUNNER, "evaluate") as evaluate:
            with (Path(directory) / "hosted-execution.lock").open("a") as lock:
                RUNNER.fcntl.flock(lock, RUNNER.fcntl.LOCK_EX | RUNNER.fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    HOSTED.main()
            evaluate.assert_not_called()


class SmokeTrialTests(unittest.TestCase):
    def test_selection_deduplicates_and_balances_length_quartiles(self):
        chunks = [SimpleNamespace(id=str(i), content_hash=str(i), content="x" * (i + 1)) for i in range(80)]
        ordered = SMOKE.representative_order(chunks + chunks)
        self.assertEqual(len(ordered), 80)
        self.assertEqual([item.id for item in ordered], [item.id for item in SMOKE.representative_order(chunks)])
        for offset in range(0, len(ordered), 4):
            self.assertEqual({int(item.id) // 20 for item in ordered[offset:offset + 4]}, {0, 1, 2, 3})

    def test_deadline_interrupts_inflight_request_and_preserves_report(self):
        provider = SimpleNamespace(embed_query=lambda _: time.sleep(1), usage_stats={})
        with tempfile.TemporaryDirectory() as directory:
            report = SMOKE.measure(provider, [], [SimpleNamespace(id="q1", text="query")], Path(directory), duration=.02)
        self.assertEqual(report["outcome"], "time_budget_reached")
        self.assertEqual(report["completed_documents"], 0)
        self.assertEqual(report["incomplete_request"], {"role": "query", "ids": ["q1"]})
        self.assertEqual(SMOKE.signal.getitimer(SMOKE.signal.ITIMER_REAL)[0], 0)


class EvaluationManifestTests(unittest.TestCase):
    def test_only_approved_runs_start(self):
        for folder in [APP / "prepare", *sorted((APP / "runs").iterdir())]:
            with self.subTest(folder=folder.name):
                documents = render(folder)
                job = next(doc for doc in documents if doc["kind"] == "Job")
                self.assertEqual(job["spec"]["suspend"], folder.name == "qwen")
                self.assertEqual(job["spec"]["backoffLimit"], 0)
                self.assertNotIn("ttlSecondsAfterFinished", job["spec"])
                pod = job["spec"]["template"]["spec"]
                self.assertFalse(pod["automountServiceAccountToken"])
                self.assertEqual(pod["restartPolicy"], "Never")
                if folder.name == "bge":
                    self.assertFalse(pod.get("initContainers"))
                    self.assertEqual(job["spec"]["activeDeadlineSeconds"], 1200)
                else:
                    database = pod["initContainers"][0]
                    self.assertEqual(database["restartPolicy"], "Always")
                    self.assertIn("listen_addresses=127.0.0.1", database["args"])
                self.assertEqual(pod["nodeSelector"]["kubernetes.io/hostname"], "hcc8")
                runner = pod["containers"][0]
                keys = [env["name"] for env in runner["env"] if "secretKeyRef" in env.get("valueFrom", {})]
                expected = {"openai": ["OPENAI_API_KEY"], "voyage": ["VOYAGE_API_KEY"], "voyage-code": ["VOYAGE_API_KEY"]}
                self.assertEqual(keys, expected.get(folder.name, []))

    def test_approval_edits_do_not_mutate_job_template(self):
        with tempfile.TemporaryDirectory() as temporary:
            import shutil

            copy = Path(temporary) / "app"
            shutil.copytree(APP, copy)
            before = next(doc for doc in render(copy / "runs/qwen") if doc["kind"] == "Job")
            (copy / "jobs/base/approval.json").write_text('{"approved": true}')
            after = next(doc for doc in render(copy / "runs/qwen") if doc["kind"] == "Job")
            self.assertEqual(before, after)

    def test_results_survive_flux_pruning(self):
        volumes = render(APP / "storage")
        artifacts = next(doc for doc in volumes if doc["metadata"]["name"].endswith("artifacts"))
        self.assertEqual(artifacts["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")


if __name__ == "__main__":
    unittest.main()
