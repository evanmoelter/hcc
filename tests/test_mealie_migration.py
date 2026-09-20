import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APOLLO = Path("kubernetes/apollo")


def documents(data):
    output = subprocess.check_output(["yq", "-o=json", "ea", "[.]"], input=data)
    return [resource for resource in json.loads(output) if resource is not None]


def build(root, owner, path):
    owner_file = root / "owner.json"
    owner_file.write_text(json.dumps(owner))
    return documents(subprocess.check_output([
        "flux", "build", "kustomization", owner["metadata"]["name"], "--dry-run",
        "--strict-substitute", "--path", str(root / path),
        "--kustomization-file", str(owner_file),
    ]))


def render():
    with tempfile.TemporaryDirectory(prefix="mealie-migration-") as directory:
        root = Path(directory)
        for path in ["apps/default", "components/postgres", "components/volsync"]:
            shutil.copytree(ROOT / APOLLO / path, root / APOLLO / path)
        parent = documents((ROOT / APOLLO / "flux/apps.yaml").read_bytes())[0]
        parent["spec"]["postBuild"] = {"substitute": {"TEST_RENDER": "true"}}
        owners = {
            resource["metadata"]["name"]: resource
            for resource in build(root, parent, APOLLO / "apps/default")
            if resource["kind"] == "Kustomization"
        }
        resources = {}
        for name, owner in owners.items():
            owner["spec"]["postBuild"].setdefault("substitute", {}).update({
                "SECRET_DOMAIN": "example.invalid", "TIMEZONE": "Etc/UTC",
            })
            resources[name] = build(root, owner, owner["spec"]["path"])
        return owners, resources


class MealieMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owners, cls.resources = render()

    def resource(self, owner, kind, name=None):
        return next(resource for resource in self.resources[owner]
                    if resource["kind"] == kind
                    and (name is None or resource["metadata"]["name"] == name))

    def test_database_recovers_from_its_apollo_archive(self):
        cluster = self.resource("mealie-database", "Cluster")
        self.assertEqual(set(cluster["spec"]["bootstrap"]), {"recovery"})
        external = next(source for source in cluster["spec"]["externalClusters"]
                        if source["name"] == cluster["spec"]["bootstrap"]["recovery"]["source"])
        writer = next(plugin for plugin in cluster["spec"]["plugins"] if plugin.get("isWALArchiver"))
        self.assertEqual(external["plugin"]["parameters"], writer["parameters"])
        self.assertEqual(writer["parameters"], {
            "barmanObjectName": "mealie-pg", "serverName": "mealie-pg-apollo-v1",
        })
        annotations = cluster["metadata"]["annotations"]
        self.assertEqual(annotations["cnpg.io/skipEmptyWalArchiveCheck"], "enabled")
        self.assertEqual(annotations["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertTrue(cluster["spec"]["imageName"].split(":", 1)[1].startswith("18."))
        self.assertEqual(cluster["spec"]["postgresql"]["parameters"], {
            "max_connections": "100", "shared_buffers": "64MB",
        })
        store = self.resource("mealie-database", "ObjectStore", "mealie-pg")
        self.assertEqual(store["spec"]["configuration"]["destinationPath"],
                         "s3://tf-hcc-apollo-cnpg/mealie/")
        secret = self.resource("mealie-database", "ExternalSecret", "mealie-pg-r2")
        remote = {entry["secretKey"]: entry["remoteRef"]["key"] for entry in secret["spec"]["data"]}
        self.assertEqual(remote["R2_ACCESS_KEY_ID"], "cnpg-r2")
        self.assertEqual(remote["R2_SECRET_ACCESS_KEY"], "cnpg-r2")

    def test_cleanup_preserves_protected_pvc_and_immutable_restore_reference(self):
        storage = self.resources["mealie-storage"]
        self.assertEqual(len(storage), 1)
        pvc = self.resource("mealie-storage", "PersistentVolumeClaim", "mealie-data")
        self.assertEqual(pvc["spec"]["dataSourceRef"], {
            "apiGroup": "volsync.backube", "kind": "ReplicationDestination",
            "name": "mealie-bootstrap-migration-v1",
        })
        self.assertEqual(pvc["spec"]["resources"]["requests"]["storage"], "5Gi")
        self.assertEqual(pvc["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        health_checks = self.owners["mealie-storage"]["spec"]["healthCheckExprs"]
        self.assertEqual([check["kind"] for check in health_checks], ["PersistentVolumeClaim"])

    def test_cleanup_removes_restore_resources_and_source_credentials(self):
        self.assertNotIn("mealie-restore-preflight", self.owners)
        resources = [resource for owned in self.resources.values() for resource in owned]
        self.assertFalse(any(resource["kind"] in {"ReplicationDestination", "Job"} for resource in resources))
        rendered = json.dumps(resources)
        for retired in ["mealie-volsync-migration", "mealie-postgres-migration", "mealie-pg-source",
                        "mealie-volsync-restore-migration-v1", "tf-hcc-cloudnativepg", "tf-hcc-volsync"]:
            with self.subTest(retired=retired):
                self.assertNotIn(retired, rendered)

    def test_new_pvc_backup_uses_apollo_repository_and_password(self):
        source = self.resource("mealie-backup", "ReplicationSource")
        secret = self.resource("mealie-backup", "ExternalSecret")
        self.assertEqual(source["spec"]["sourcePVC"], "mealie-data")
        self.assertEqual(source["spec"]["restic"]["repository"], secret["spec"]["target"]["name"])
        self.assertTrue(secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-apollo-volsync/mealie"))
        remote = {entry["secretKey"]: entry["remoteRef"]["key"] for entry in secret["spec"]["data"]}
        self.assertEqual(remote["RESTIC_PASSWORD"], "mealie")
        self.assertEqual(remote["R2_ACCESS_KEY_ID"], "volsync-r2")

    def test_app_and_backup_dependencies(self):
        required = {
            "mealie-storage": {"longhorn-config"},
            "mealie-database": {"plugin-barman-cloud", "longhorn-config", "onepassword-store"},
            "mealie": {"mealie-storage", "mealie-database", "onepassword-store",
                       "envoy-gateway-config", "cloudflare-dns", "unifi-dns"},
            "mealie-backup": {"mealie", "volsync", "onepassword-store"},
        }
        graph = {name: {dependency["name"] for dependency in owner["spec"].get("dependsOn", [])}
                 for name, owner in self.owners.items()}
        self.assertEqual(graph["mealie-storage"], {"longhorn-config"})
        for name, dependencies in required.items():
            self.assertLessEqual(dependencies, graph[name])
            self.assertTrue(self.owners[name]["spec"]["wait"])
        pending = set(graph)
        while pending:
            ready = {name for name in pending if not graph[name] & pending}
            self.assertTrue(ready, f"Dependency cycle: {pending}")
            pending -= ready
        self.assertFalse(self.owners["mealie-backup"]["spec"].get("suspend", False))
        app_resources = self.resources["mealie"]
        self.assertFalse(any(resource["kind"] in {"Ingress", "HTTPRoute"} for resource in app_resources))
        values = self.resource("mealie", "HelmRelease")["spec"]["values"]
        self.assertFalse(values.get("ingress"))
        self.assertTrue(values["route"])
        for route in values["route"].values():
            self.assertIs(route["enabled"], True)


if __name__ == "__main__":
    unittest.main()
