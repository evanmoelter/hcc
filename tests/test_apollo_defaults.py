import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APOLLO = ROOT / "kubernetes/apollo"
HELM_OPT_OUT = "helm-defaults.flux.home.arpa/disabled"


def documents(data):
    result = subprocess.check_output(["yq", "-o=json", "ea", "[.]"], input=data)
    return [document for document in json.loads(result) if document is not None]


def read(path):
    return documents(path.read_bytes())[0]


def write(path, document):
    path.write_text(json.dumps(document))


def build(owner, path):
    owner = copy.deepcopy(owner)
    owner["spec"].setdefault("postBuild", {}).pop("substituteFrom", None)
    owner["spec"]["postBuild"].setdefault("substitute", {}).update({
        "SECRET_DOMAIN": "example.test", "TIMEZONE": "Etc/UTC",
    })
    with tempfile.TemporaryDirectory(prefix="apollo-defaults-owner-") as directory:
        owner_path = Path(directory) / "owner.json"
        write(owner_path, owner)
        return documents(subprocess.check_output([
            "flux", "build", "kustomization", owner["metadata"]["name"], "--dry-run",
            "--path", str(path), "--kustomization-file", str(owner_path),
        ]))


def synthetic_release(opt_out):
    with tempfile.TemporaryDirectory(prefix="apollo-defaults-fixture-") as directory:
        root = Path(directory)
        app = root / "app"
        app.mkdir()
        owner = {
            "apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
            "metadata": {"name": "example", "namespace": "flux-system"},
            "spec": {
                "interval": "30m", "path": "./app", "prune": True,
                "sourceRef": {"kind": "GitRepository", "name": "home-kubernetes"},
            },
        }
        if opt_out:
            owner["metadata"]["labels"] = {HELM_OPT_OUT: "true"}
            owner["spec"]["patches"] = [{
                "target": {"group": "helm.toolkit.fluxcd.io", "kind": "HelmRelease"},
                "patch": json.dumps([{
                    "op": "add", "path": "/spec/values", "value": {"customPatchSurvived": True},
                }]),
            }]
        write(root / "owner.json", owner)
        write(root / "kustomization.yaml", {
            "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": ["owner.json"],
        })
        write(app / "kustomization.yaml", {
            "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": ["helmrelease.json"],
        })
        write(app / "helmrelease.json", {
            "apiVersion": "helm.toolkit.fluxcd.io/v2", "kind": "HelmRelease",
            "metadata": {"name": "example", "namespace": "default"},
            "spec": {
                "interval": "30m", "chartRef": {"kind": "OCIRepository", "name": "example"},
                "timeout": "17m",
                "install": {"crds": "Skip", "remediation": {"retries": 7}},
                "upgrade": {"crds": "Skip", "remediation": {"retries": 7}},
            },
        })
        rendered_owner = build(read(APOLLO / "flux/apps.yaml"), root)[0]
        return owner, rendered_owner, build(rendered_owner, app)[0]


class ApolloDefaultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = build(read(APOLLO / "flux/apps.yaml"), APOLLO / "apps")
        cls.owners = {resource["metadata"]["name"]: resource for resource in cls.resources
                      if resource["kind"] == "Kustomization"}

    def test_namespaces_keep_names_pruning_protection_and_security_policy(self):
        namespaces = {resource["metadata"]["name"]: resource for resource in self.resources
                      if resource["kind"] == "Namespace"}
        expected = {
            "database": "restricted", "flux-system": None, "kube-system": None,
            "monitoring": "privileged", "network": "restricted", "security": "restricted",
            "storage": "privileged",
        }
        self.assertEqual(set(namespaces), set(expected))
        for name, security_policy in expected.items():
            with self.subTest(namespace=name):
                metadata = namespaces[name]["metadata"]
                protection = {**metadata.get("labels", {}), **metadata.get("annotations", {})}
                self.assertEqual(protection.get("kustomize.toolkit.fluxcd.io/prune"), "disabled")
                self.assertEqual(metadata.get("labels", {}).get("pod-security.kubernetes.io/enforce"),
                                 security_policy)
                self.assertNotIn("namespace", metadata)

    def test_namespace_component_does_not_move_flux_kustomizations(self):
        self.assertTrue(self.owners)
        for name, owner in self.owners.items():
            with self.subTest(kustomization=name):
                self.assertEqual(owner["metadata"]["namespace"], "flux-system")

    def test_deletion_defaults_preserve_critical_orphan_exceptions(self):
        for name, owner in self.owners.items():
            with self.subTest(kustomization=name):
                if name in {"cilium", "flux-instance"}:
                    self.assertFalse(owner["spec"]["prune"])
                    self.assertEqual(owner["spec"]["deletionPolicy"], "Orphan")
                else:
                    self.assertEqual(owner["spec"]["deletionPolicy"], "WaitForTermination")

    def test_application_release_receives_defaults_through_parent_and_child_builds(self):
        owner = self.owners["echo-server"]
        resources = build(owner, ROOT / owner["spec"]["path"])
        release = next(resource for resource in resources if resource["kind"] == "HelmRelease")
        self.assert_defaults(release)

    def test_dns_releases_keep_their_crd_policy(self):
        for name in ["cloudflare-dns", "unifi-dns"]:
            with self.subTest(release=name):
                owner = self.owners[name]
                self.assertEqual(owner["metadata"]["labels"][HELM_OPT_OUT], "true")
                resources = build(owner, ROOT / owner["spec"]["path"])
                spec = next(resource["spec"] for resource in resources if resource["kind"] == "HelmRelease")
                self.assertEqual(spec["install"]["crds"], "Skip")
                self.assertEqual(spec["upgrade"]["crds"], "Skip")

    def test_local_fields_cannot_override_parent_defaults(self):
        _, _, release = synthetic_release(opt_out=False)
        self.assert_defaults(release)
        self.assertEqual(release["spec"]["timeout"], "17m")

    def test_opt_out_preserves_custom_child_patches_and_local_policy(self):
        original, owner, release = synthetic_release(opt_out=True)
        self.assertEqual(owner["spec"]["patches"], original["spec"]["patches"])
        self.assertEqual(owner["spec"]["deletionPolicy"], "WaitForTermination")
        self.assertEqual(release["spec"]["values"], {"customPatchSurvived": True})
        self.assertEqual(release["spec"]["install"]["crds"], "Skip")
        self.assertEqual(release["spec"]["install"]["remediation"]["retries"], 7)
        self.assertEqual(release["spec"]["upgrade"]["crds"], "Skip")
        self.assertEqual(release["spec"]["upgrade"]["remediation"]["retries"], 7)

    def assert_defaults(self, release):
        spec = release["spec"]
        self.assertEqual(spec["install"]["crds"], "CreateReplace")
        self.assertEqual(spec["install"]["strategy"]["name"], "RemediateOnFailure")
        self.assertEqual(spec["install"]["remediation"]["retries"], 3)
        self.assertEqual(spec["upgrade"]["crds"], "CreateReplace")
        self.assertEqual(spec["upgrade"]["strategy"]["name"], "RemediateOnFailure")
        self.assertTrue(spec["upgrade"]["cleanupOnFail"])
        self.assertEqual(spec["upgrade"]["remediation"]["retries"], 3)
        self.assertTrue(spec["upgrade"]["remediation"]["remediateLastFailure"])
        self.assertEqual(spec["rollback"], {"cleanupOnFail": True})


if __name__ == "__main__":
    unittest.main()
