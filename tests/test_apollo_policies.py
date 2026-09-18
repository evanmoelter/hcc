from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = """apiVersion: v1
kind: Namespace
metadata:
  name: example
  annotations:
    kustomize.toolkit.fluxcd.io/prune: disabled
"""
MISSING_POLICY = """apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: missing-policy
spec:
  prune: false
"""


class ApolloPolicyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cluster = Path(self.temporary.name) / "apollo"
        for directory in ("apps", "flux", "components"):
            (self.cluster / directory).mkdir(parents=True)

    def run_lint(self, cluster=None):
        return subprocess.run(
            ["bash", str(ROOT / "scripts/lint-apollo.sh"), str(cluster or self.cluster)],
            capture_output=True, text=True,
        )

    def test_second_document_is_checked_in_every_source_directory(self):
        for directory in ("apps", "flux", "components"):
            with self.subTest(directory=directory):
                manifest = self.cluster / directory / "arbitrary name.yml"
                manifest.write_text(NAMESPACE + "---\n" + MISSING_POLICY)
                result = self.run_lint()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("missing-policy must declare spec.deletionPolicy", result.stdout)
                manifest.unlink()

    def test_encrypted_files_are_not_parsed(self):
        (self.cluster / "apps/namespace.yaml").write_text(NAMESPACE)
        for suffix in ("yaml", "yml"):
            (self.cluster / f"apps/secret.sops.{suffix}").write_text("not valid YAML: [")
        result = self.run_lint()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_tree_fails(self):
        result = self.run_lint()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No Apollo manifests found", result.stderr)

    def test_missing_source_directory_is_reported(self):
        for directory in ("apps", "flux", "components"):
            with self.subTest(directory=directory):
                missing = self.cluster / directory
                missing.rmdir()
                result = self.run_lint()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"Missing Apollo source directory: {missing}", result.stderr)
                missing.mkdir()

    def test_old_cluster_is_rejected(self):
        result = self.run_lint(self.cluster.parent / "main")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only apply to the apollo cluster", result.stderr)
