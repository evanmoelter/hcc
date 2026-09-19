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

    def test_database_requires_old_archive_and_preserves_source(self):
        cluster = self.resource("mealie-database", "Cluster")
        bootstrap = cluster["spec"]["bootstrap"]
        self.assertEqual(set(bootstrap), {"recovery"})
        external = next(source for source in cluster["spec"]["externalClusters"]
                        if source["name"] == bootstrap["recovery"]["source"])
        source_parameters = external["plugin"]["parameters"]
        writer_parameters = next(plugin for plugin in cluster["spec"]["plugins"]
                                 if plugin.get("isWALArchiver"))["parameters"]
        source = self.resource("mealie-database", "ObjectStore", source_parameters["barmanObjectName"])
        writer = self.resource("mealie-database", "ObjectStore", writer_parameters["barmanObjectName"])
        self.assertEqual(source_parameters["serverName"], "mealie-pg-v1")
        self.assertEqual(writer_parameters["serverName"], "mealie-pg-apollo-v1")
        self.assertEqual(source["spec"]["configuration"]["destinationPath"], "s3://tf-hcc-cloudnativepg/")
        self.assertEqual(writer["spec"]["configuration"]["destinationPath"], "s3://tf-hcc-apollo-cnpg/mealie/")
        self.assertNotEqual(source["spec"]["configuration"]["s3Credentials"],
                            writer["spec"]["configuration"]["s3Credentials"])
        self.assertNotIn("retentionPolicy", source["spec"])
        self.assertNotIn("cnpg.io/skipEmptyWalArchiveCheck", cluster["metadata"]["annotations"])
        self.assertEqual(cluster["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertTrue(cluster["spec"]["imageName"].split(":", 1)[1].startswith("18."))

    def test_database_stores_use_their_own_credentials_and_shared_account(self):
        for store_name, item in [("mealie-pg-source", "mealie-postgres-migration"), ("mealie-pg", "cnpg-r2")]:
            with self.subTest(store=store_name):
                store = self.resource("mealie-database", "ObjectStore", store_name)
                credentials = store["spec"]["configuration"]["s3Credentials"]
                secret_name = credentials["accessKeyId"]["name"]
                self.assertEqual(credentials["secretAccessKey"]["name"], secret_name)
                secret = self.resource("mealie-database", "ExternalSecret", secret_name)
                remote = {entry["secretKey"]: entry["remoteRef"] for entry in secret["spec"]["data"]}
                self.assertEqual(remote["ACCOUNT_ID"]["key"], "cloudflare-r2")
                self.assertEqual(remote["R2_ACCESS_KEY_ID"]["key"], item)
                self.assertEqual(remote["R2_SECRET_ACCESS_KEY"]["key"], item)
                endpoint = next(env for env in store["spec"]["instanceSidecarConfiguration"]["env"]
                                if env["name"] == "AWS_ENDPOINT_URL_S3")
                self.assertEqual(endpoint["valueFrom"]["secretKeyRef"],
                                 {"name": secret_name, "key": "ENDPOINT_URL"})

    def test_pvc_cannot_start_empty_or_restore_from_new_backup_repository(self):
        pvc = self.resource("mealie-storage", "PersistentVolumeClaim", "mealie-data")
        destination = self.resource("mealie-storage", "ReplicationDestination")
        self.assertEqual(pvc["spec"]["dataSourceRef"], {
            "apiGroup": "volsync.backube", "kind": "ReplicationDestination",
            "name": destination["metadata"]["name"],
        })
        self.assertEqual(pvc["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        secret = self.resource("mealie-preflight", "ExternalSecret")
        self.assertEqual(destination["spec"]["restic"]["repository"], secret["spec"]["target"]["name"])
        template = secret["spec"]["target"]["template"]["data"]
        self.assertTrue(template["RESTIC_REPOSITORY"].endswith("/tf-hcc-volsync/mealie-data"))
        remote = {entry["secretKey"]: entry["remoteRef"]["key"] for entry in secret["spec"]["data"]}
        self.assertEqual(remote["RESTIC_PASSWORD"], "mealie-volsync-migration")
        self.assertEqual(remote["R2_ACCESS_KEY_ID"], "mealie-volsync-migration")
        preflight = self.resource("mealie-preflight", "Job")
        self.assertIn({"secretRef": {"name": secret["spec"]["target"]["name"]}},
                      preflight["spec"]["template"]["spec"]["containers"][0]["envFrom"])

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

    def test_restore_dependencies_and_manual_publication_gates(self):
        required = {
            "mealie-preflight": {"onepassword-store"},
            "mealie-storage": {"mealie-preflight", "volsync", "longhorn-config"},
            "mealie-database": {"plugin-barman-cloud", "longhorn-config", "onepassword-store"},
            "mealie": {"mealie-storage", "mealie-database", "onepassword-store",
                       "envoy-gateway-config", "cloudflare-dns", "unifi-dns", "tailscale-config"},
            "mealie-backup": {"mealie", "volsync", "onepassword-store"},
        }
        graph = {name: {dependency["name"] for dependency in owner["spec"].get("dependsOn", [])}
                 for name, owner in self.owners.items()}
        for name, dependencies in required.items():
            self.assertLessEqual(dependencies, graph[name])
            self.assertTrue(self.owners[name]["spec"]["wait"])
        pending = set(graph)
        while pending:
            ready = {name for name in pending if not graph[name] & pending}
            self.assertTrue(ready, f"Dependency cycle: {pending}")
            pending -= ready
        self.assertTrue(self.owners["mealie-backup"]["spec"]["suspend"])
        app_resources = self.resources["mealie"]
        self.assertFalse(any(resource["kind"] in {"Ingress", "HTTPRoute"} for resource in app_resources))
        values = self.resource("mealie", "HelmRelease")["spec"]["values"]
        self.assertTrue(values["ingress"])
        for ingress in values["ingress"].values():
            self.assertIs(ingress["enabled"], False)
        self.assertTrue(values["route"])
        for route in values["route"].values():
            self.assertIs(route["enabled"], False)


if __name__ == "__main__":
    unittest.main()
