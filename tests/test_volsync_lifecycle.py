import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = Path("kubernetes/apollo/apps/storage/volsync-test")
COMPONENTS = Path("kubernetes/apollo/components/volsync")
PATCHES = ROOT / "tests/fixtures/volsync-test"


def command(*args, cwd=None, data=None, env=None):
    return subprocess.check_output(args, cwd=cwd, input=data, env=env)


def yaml_documents(data):
    return json.loads(command("yq", "-o=json", "ea", "[.]", data=data))


def render(root):
    namespace = yaml_documents((root / APP.parent / "kustomization.yaml").read_bytes())[0]
    owners = {}
    for resource in namespace["resources"]:
        if resource.startswith("./volsync-test/"):
            for owner in yaml_documents((root / APP.parent / resource).read_bytes()):
                owners[owner["metadata"]["name"]] = owner
    rendered = {}
    for name, owner in owners.items():
        spec = owner["spec"]
        path = root / spec["path"]
        config_path = path / "kustomization.yaml"
        original = config_path.read_bytes()
        config = yaml_documents(original)[0]
        config["components"] = config.get("components", []) + spec.get("components", [])
        config["patches"] = config.get("patches", []) + spec.get("patches", [])
        config["namespace"] = spec["targetNamespace"]
        try:
            config_path.write_text(json.dumps(config))
            manifests = command("kustomize", "build", str(path))
            manifests = command(
                "flux", "envsubst", data=manifests,
                env=os.environ | spec.get("postBuild", {}).get("substitute", {}),
            )
            rendered[name] = yaml_documents(manifests)
        finally:
            config_path.write_bytes(original)
    return owners, rendered


class VolsyncLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory(prefix="volsync-lifecycle-") as directory:
            root = Path(directory)
            shutil.copytree(ROOT / APP, root / APP)
            shutil.copytree(ROOT / COMPONENTS, root / COMPONENTS)
            shutil.copy2(ROOT / APP.parent / "kustomization.yaml", root / APP.parent)
            owners = yaml_documents((root / APP / "ks-storage.yaml").read_bytes())
            if "volsync-test-preflight" not in [owner["metadata"]["name"] for owner in owners]:
                job = yaml_documents((root / APP / "app/job.yaml").read_bytes())[0]
                if job["metadata"]["name"] == "volsync-test-verify-post-cleanup-v2":
                    command("git", "apply", "--reverse", str(PATCHES / "verify-cleanup.patch"), cwd=root)
                command("git", "apply", "--reverse", str(PATCHES / "cleanup.patch"), cwd=root)
            cls.recovery = render(root)
            command("git", "apply", str(PATCHES / "cleanup.patch"), cwd=root)
            cls.cleaned = render(root)
            command("git", "apply", str(PATCHES / "verify-cleanup.patch"), cwd=root)
            cls.verified = render(root)

    def resource(self, state, owner, kind):
        resources = [r for r in state[1][owner] if r["kind"] == kind]
        self.assertEqual(len(resources), 1)
        return resources[0]

    def test_recovery_dependencies_gate_each_stage(self):
        chain = [
            "volsync-test-fixture", "volsync-test-fixture-backup", "volsync-test-preflight",
            "volsync-test-storage", "volsync-test", "volsync-test-backup",
        ]
        self.assertEqual(set(self.recovery[0]), set(chain))
        for before, after in zip(chain, chain[1:]):
            spec = self.recovery[0][after]["spec"]
            self.assertIn(before, [d["name"] for d in spec["dependsOn"]])
            self.assertTrue(self.recovery[0][before]["spec"]["wait"])

    def test_claim_refers_to_exact_restore_destination(self):
        pvc = self.resource(self.recovery, "volsync-test-storage", "PersistentVolumeClaim")
        destination = self.resource(self.recovery, "volsync-test-storage", "ReplicationDestination")
        self.assertEqual(pvc["spec"]["dataSourceRef"], {
            "apiGroup": "volsync.backube", "kind": "ReplicationDestination",
            "name": destination["metadata"]["name"],
        })
        self.assertEqual(destination["spec"]["trigger"], {"manual": "v2"})
        checks = self.recovery[0]["volsync-test-storage"]["spec"]["healthCheckExprs"]
        self.assertEqual({c["kind"] for c in checks}, {"PersistentVolumeClaim", "ReplicationDestination"})

    def test_restore_retains_clone_source_until_cleanup(self):
        destination = self.resource(self.recovery, "volsync-test-storage", "ReplicationDestination")
        restic = destination["spec"]["restic"]
        self.assertEqual(restic["copyMethod"], "Snapshot")
        self.assertFalse(restic["cleanupTempPVC"])
        self.assertTrue(restic["cleanupCachePVC"])

    def test_retry_uses_fresh_preflight_and_matching_credentials(self):
        job = self.resource(self.recovery, "volsync-test-preflight", "Job")
        secret = self.resource(self.recovery, "volsync-test-preflight", "ExternalSecret")
        destination = self.resource(self.recovery, "volsync-test-storage", "ReplicationDestination")
        self.assertEqual(job["metadata"]["name"], "volsync-test-preflight-v2")
        self.assertEqual(destination["metadata"]["name"], "volsync-test-bootstrap-v2")
        repository = destination["spec"]["restic"]["repository"]
        self.assertEqual(repository, secret["spec"]["target"]["name"])
        container = job["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["envFrom"], [{"secretRef": {"name": repository}}])

    def test_backups_use_distinct_paths_and_correct_claims(self):
        for owner, claim, path, trigger in [
            ("volsync-test-fixture-backup", "volsync-test-source", "volsync-test/fixture", "v1"),
            ("volsync-test-backup", "volsync-test-restored-v2", "volsync-test/app", "v2"),
        ]:
            source = self.resource(self.recovery, owner, "ReplicationSource")
            secret = self.resource(self.recovery, owner, "ExternalSecret")
            self.assertEqual(source["spec"]["sourcePVC"], claim)
            self.assertEqual(source["spec"]["trigger"], {"manual": trigger})
            self.assertTrue(secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
                "/tf-hcc-apollo-volsync/" + path,
            ))
            refs = {d["secretKey"]: d["remoteRef"] for d in secret["spec"]["data"]}
            self.assertEqual(refs["R2_ACCESS_KEY_ID"]["key"], "volsync-r2")
            self.assertEqual(refs["RESTIC_PASSWORD"]["key"], "volsync-test")
        restore_secret = self.resource(self.recovery, "volsync-test-preflight", "ExternalSecret")
        self.assertTrue(restore_secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-apollo-volsync/volsync-test/fixture",
        ))

    def test_cleanup_keeps_same_claim_and_owner(self):
        for state in [self.cleaned, self.verified]:
            self.assertEqual(set(state[0]), {"volsync-test", "volsync-test-storage", "volsync-test-backup"})
            self.assertEqual(
                self.resource(self.recovery, "volsync-test-storage", "PersistentVolumeClaim"),
                self.resource(state, "volsync-test-storage", "PersistentVolumeClaim"),
            )
            storage = state[0]["volsync-test-storage"]["spec"]
            self.assertEqual(storage["dependsOn"], [{"name": "longhorn-config"}])
            self.assertEqual(storage["healthCheckExprs"], [
                c for c in self.recovery[0]["volsync-test-storage"]["spec"]["healthCheckExprs"]
                if c["kind"] == "PersistentVolumeClaim"
            ])

    def test_cleanup_removes_all_restore_and_fixture_resources(self):
        remaining = [r for resources in self.cleaned[1].values() for r in resources]
        self.assertNotIn("ReplicationDestination", [r["kind"] for r in remaining])
        self.assertEqual([r["metadata"]["name"] for r in remaining if r["kind"] == "ExternalSecret"],
                         ["volsync-test-volsync"])
        self.assertEqual([r["metadata"]["name"] for r in remaining if r["kind"] == "Job"],
                         ["volsync-test-verify-v2"])
        self.assertEqual([r["metadata"]["name"] for r in remaining if r["kind"] == "ReplicationSource"],
                         ["volsync-test-r2"])

    def test_post_cleanup_verifier_is_fresh_and_uses_same_volume(self):
        before = self.resource(self.cleaned, "volsync-test", "Job")
        after = self.resource(self.verified, "volsync-test", "Job")
        expected = copy.deepcopy(before)
        expected["metadata"]["name"] = "volsync-test-verify-post-cleanup-v2"
        self.assertEqual(after, expected)
        claims = [v["persistentVolumeClaim"] for v in after["spec"]["template"]["spec"]["volumes"]
                  if "persistentVolumeClaim" in v]
        self.assertEqual(claims, [{"claimName": "volsync-test-restored-v2", "readOnly": True}])
        self.assertEqual(self.cleaned[1]["volsync-test-backup"], self.verified[1]["volsync-test-backup"])


if __name__ == "__main__":
    unittest.main()
