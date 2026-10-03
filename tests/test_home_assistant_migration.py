import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APOLLO = Path("kubernetes/apollo")
APP = APOLLO / "apps/default/home-assistant"


def documents(data):
    output = subprocess.check_output(["yq", "-o=json", "ea", "[.]"], input=data)
    return [resource for resource in json.loads(output) if resource is not None]


def read(path):
    return documents(path.read_bytes())[0]


def render():
    with tempfile.TemporaryDirectory(prefix="home-assistant-migration-") as directory:
        root = Path(directory)
        for path in ["apps/default/home-assistant", "components/postgres", "components/volsync"]:
            shutil.copytree(ROOT / APOLLO / path, root / APOLLO / path)
        owners = {
            resource["metadata"]["name"]: resource
            for filename in ["ks.yaml", "ks-storage.yaml", "ks-database.yaml", "ks-tailscale.yaml"]
            for resource in documents((root / APP / filename).read_bytes())
        }
        resources = {}
        for name, owner in owners.items():
            owner["spec"].setdefault("postBuild", {}).setdefault("substitute", {}).update({
                "SECRET_DOMAIN": "example.invalid", "TIMEZONE": "Etc/UTC", "CLUSTER_CIDR": "10.70.0.0/16",
            })
            owner_file = root / "owner.json"
            owner_file.write_text(json.dumps(owner))
            resources[name] = documents(subprocess.check_output([
                "flux", "build", "kustomization", name, "--dry-run", "--strict-substitute",
                "--path", str(root / owner["spec"]["path"]), "--kustomization-file", str(owner_file),
            ]))
        return owners, resources


class HomeAssistantMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owners, cls.resources = render()

    def resource(self, owner, kind, name=None):
        return next(resource for resource in self.resources[owner]
                    if resource["kind"] == kind
                    and (name is None or resource["metadata"]["name"] == name))

    def test_old_disable_preserves_database_claims_and_matter_for_rollback(self):
        app = ROOT / "kubernetes/main/apps/default/home-assistant/app"
        resources = set(read(app / "kustomization.yaml")["resources"])
        self.assertLessEqual({"./cluster.yaml", "./pvc.yaml", "./helmrelease.yaml",
                              "./config-volsync-r2.yaml", "./scheduledbackup.yaml"}, resources)
        values = read(app / "helmrelease.yaml")["spec"]["values"]
        self.assertEqual(values["controllers"]["home-assistant"]["replicas"], 0)
        self.assertTrue(all(ingress.get("enabled") is False for ingress in values["ingress"].values()))
        self.assertIn("matter-server", values["controllers"]["home-assistant"]["containers"])
        claims = {claim["metadata"]["name"] for claim in documents((app / "pvc.yaml").read_bytes())}
        self.assertEqual(claims, {"home-assistant-config", "home-assistant-matter-data"})
        self.assertEqual(values["persistence"]["matter-data"]["existingClaim"], "home-assistant-matter-data")
        self.assertEqual(read(app / "cluster.yaml")["spec"]["instances"], 1)
        namespace = read(ROOT / "kubernetes/main/apps/default/kustomization.yaml")
        self.assertIn(Path("home-assistant/ks.yaml"), {Path(resource) for resource in namespace["resources"]})

    def test_database_recovery_and_writer_use_apollo_archive_after_cleanup(self):
        cluster = self.resource("home-assistant-database", "Cluster")
        spec = cluster["spec"]
        recovery = spec["bootstrap"]["recovery"]
        self.assertEqual((recovery["database"], recovery["owner"]), ("home_assistant", "home_assistant"))
        source = next(source for source in spec["externalClusters"] if source["name"] == recovery["source"])
        writer = next(plugin for plugin in spec["plugins"] if plugin.get("isWALArchiver"))
        self.assertEqual(source["plugin"]["parameters"], writer["parameters"])
        self.assertEqual(writer["parameters"]["serverName"], "home-assistant-pg-apollo-v1")
        store = self.resource("home-assistant-database", "ObjectStore", writer["parameters"]["barmanObjectName"])
        config = store["spec"]["configuration"]
        self.assertEqual(config["destinationPath"], "s3://tf-hcc-apollo-cnpg/home-assistant/")
        for reference in config["s3Credentials"].values():
            secret = self.resource("home-assistant-database", "ExternalSecret", reference["name"])
            field = next(field for field in secret["spec"]["data"] if field["secretKey"] == reference["key"])
            self.assertEqual(field["remoteRef"]["key"], "cnpg-r2")
        self.assertEqual(cluster["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertNotIn("cnpg.io/skipEmptyWalArchiveCheck", cluster["metadata"]["annotations"])
        self.assertEqual(spec["postgresql"]["parameters"], {"max_connections": "100", "shared_buffers": "128MB"})
        self.assertTrue(spec["imageName"].startswith("ghcr.io/cloudnative-pg/postgresql:18.1-system-trixie@sha256:"))

    def test_cleanup_preserves_bound_claim_without_temporary_restore_resources(self):
        claim = self.resource("home-assistant-storage", "PersistentVolumeClaim")
        self.assertEqual(claim["spec"]["dataSourceRef"], {
            "apiGroup": "volsync.backube", "kind": "ReplicationDestination",
            "name": "home-assistant-config-bootstrap-migration-v1",
        })
        self.assertEqual(claim["spec"]["resources"]["requests"]["storage"], "5Gi")
        self.assertEqual(claim["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertNotIn("home-assistant-restore-preflight", self.owners)
        for resources in self.resources.values():
            self.assertFalse(any(resource["kind"] == "ReplicationDestination" for resource in resources))
        rendered = json.dumps(self.resources)
        for removed in ["tf-hcc-volsync/", "tf-hcc-cloudnativepg/", "home-assistant-migration",
                        "home-assistant-pg-migration", "home-assistant-pg-source"]:
            self.assertNotIn(removed, rendered)
        checks = self.owners["home-assistant-storage"]["spec"]["healthCheckExprs"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["kind"], "PersistentVolumeClaim")
        self.assertIn("'Bound'", checks[0]["current"])

    def test_backup_is_enabled_and_uses_separate_apollo_repository(self):
        self.assertFalse(self.owners["home-assistant-backup"]["spec"].get("suspend", False))
        source = self.resource("home-assistant-backup", "ReplicationSource")
        self.assertEqual(source["spec"]["sourcePVC"], "home-assistant-config")
        secret = self.resource("home-assistant-backup", "ExternalSecret", source["spec"]["restic"]["repository"])
        self.assertTrue(secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-apollo-volsync/home-assistant-config"))
        fields = {field["secretKey"]: field["remoteRef"]["key"] for field in secret["spec"]["data"]}
        self.assertEqual(fields["RESTIC_PASSWORD"], "home-assistant-config")
        for field in ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]:
            self.assertEqual(fields[field], "volsync-r2")
    def test_application_uses_restored_data_without_matter_thread_or_usb(self):
        values = self.resource("home-assistant", "HelmRelease")["spec"]["values"]
        controller = values["controllers"]["home-assistant"]
        self.assertEqual(controller["replicas"], 1)
        self.assertEqual(controller["strategy"], "Recreate")
        self.assertEqual(values["persistence"]["config"]["existingClaim"], "home-assistant-config")
        db = controller["containers"]["app"]["env"]["HASS_RECORDER_DB_URL"]["valueFrom"]["secretKeyRef"]
        self.assertEqual(db, {"name": "home-assistant-pg-app", "key": "uri"})
        rendered = json.dumps(self.resources).lower()
        for excluded in ["matter-server", "matter-data", "otbr", "hostpath", "/dev/serial", "/dev/bus/usb"]:
            self.assertNotIn(excluded, rendered)
        self.assertFalse(controller["pod"].get("hostNetwork", False))
        affinity = controller["pod"]["affinity"]["nodeAffinity"]
        for term in affinity["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]:
            self.assertIn({"key": "network.home.arpa/iot-ipv4", "operator": "In", "values": ["true"]},
                          term["matchExpressions"])
        preferences = affinity["preferredDuringSchedulingIgnoredDuringExecution"]
        self.assertTrue(any({"key": "kubernetes.io/hostname", "operator": "In", "values": ["hcc6"]}
                            in item["preference"]["matchExpressions"] for item in preferences))
        self.assertNotIn("nodeSelector", controller["pod"])

    def test_private_routes_and_lifecycle_dependency_order(self):
        values = self.resource("home-assistant", "HelmRelease")["spec"]["values"]
        self.assertEqual(set(values["route"]), {"internal", "code-server"})
        for route in values["route"].values():
            self.assertTrue(all(parent["name"] == "envoy-internal" for parent in route["parentRefs"]))
        ingress = self.resource("home-assistant-tailscale", "Ingress")
        self.assertEqual(ingress["spec"]["ingressClassName"], "tailscale")
        self.assertEqual(ingress["spec"]["tls"][0]["hosts"], ["ha"])
        self.assertEqual(ingress["spec"]["defaultBackend"]["service"]["name"],
                         values["service"]["app"]["forceRename"])
        required = {
            "home-assistant-storage": {"longhorn-config"},
            "home-assistant-database": {"plugin-barman-cloud", "longhorn-config", "onepassword-store"},
            "home-assistant": {"home-assistant-storage", "home-assistant-database", "multus-config"},
            "home-assistant-backup": {"home-assistant", "volsync", "onepassword-store"},
            "home-assistant-tailscale": {"home-assistant", "tailscale-config"},
        }
        for name, expected in required.items():
            spec = self.owners[name]["spec"]
            self.assertLessEqual(expected, {dependency["name"] for dependency in spec["dependsOn"]})
            self.assertTrue(spec["wait"])


if __name__ == "__main__":
    unittest.main()
