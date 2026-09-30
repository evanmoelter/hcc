import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


def document(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(path)]))


class AuthentikShutdownTest(unittest.TestCase):
    def test_old_workloads_and_public_ingresses_are_disabled(self):
        path = ROOT / "kubernetes/main/apps/security/authentik/app"
        values = document(path / "helmrelease.yaml")["spec"]["values"]
        for component in ["server", "worker"]:
            self.assertEqual(values[component]["replicas"], 0)
            self.assertFalse(values[component]["autoscaling"]["enabled"])
        self.assertFalse(values["server"]["ingress"]["enabled"])
        webfinger = document(path / "webfinger.yaml")["spec"]["values"]
        self.assertEqual(webfinger["controllers"]["webfinger"]["replicas"], 0)
        self.assertFalse(webfinger["ingress"]["webfinger"]["enabled"])
        resources = document(path / "kustomization.yaml")["resources"]
        self.assertIn("./internal-ingress.yaml", resources)
        self.assertIn("./secret.sops.yaml", resources)


if __name__ == "__main__":
    unittest.main()
