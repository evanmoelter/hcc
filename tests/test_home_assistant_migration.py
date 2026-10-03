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


def render(config_capacity=None):
    with tempfile.TemporaryDirectory(prefix="home-assistant-migration-") as directory:
        root = Path(directory)
        for path in ["apps/default/home-assistant", "components/postgres", "components/volsync"]:
            shutil.copytree(ROOT / APOLLO / path, root / APOLLO / path)
        if config_capacity:
            pvc_file = root / APP / "storage/pvc.yaml"
            claim = read(pvc_file)
            claim["spec"]["resources"]["requests"]["storage"] = config_capacity
            pvc_file.write_text(json.dumps(claim))
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

    def test_physical_recovery_keeps_old_archive_separate_from_apollo_writer(self):
        cluster = self.resource("home-assistant-database", "Cluster")
        spec = cluster["spec"]
        self.assertEqual(set(spec["bootstrap"]), {"recovery"})
        recovery = spec["bootstrap"]["recovery"]
        self.assertEqual((recovery["database"], recovery["owner"]), ("home_assistant", "home_assistant"))
        source = next(source for source in spec["externalClusters"] if source["name"] == recovery["source"])
        source_parameters = source["plugin"]["parameters"]
        writer = next(plugin for plugin in spec["plugins"] if plugin.get("isWALArchiver"))
        self.assertEqual(source_parameters["serverName"], "home-assistant-pg-v1")
        self.assertEqual(writer["parameters"]["serverName"], "home-assistant-pg-apollo-v1")
        source_store = self.resource("home-assistant-database", "ObjectStore", source_parameters["barmanObjectName"])
        writer_store = self.resource("home-assistant-database", "ObjectStore", writer["parameters"]["barmanObjectName"])
        self.assertNotIn("retentionPolicy", source_store["spec"])
        for store, destination, credential in [
            (source_store, "s3://tf-hcc-cloudnativepg/", "home-assistant-pg-migration"),
            (writer_store, "s3://tf-hcc-apollo-cnpg/home-assistant/", "cnpg-r2"),
        ]:
            config = store["spec"]["configuration"]
            self.assertEqual(config["destinationPath"], destination)
            for reference in config["s3Credentials"].values():
                secret = self.resource("home-assistant-database", "ExternalSecret", reference["name"])
                field = next(field for field in secret["spec"]["data"] if field["secretKey"] == reference["key"])
                self.assertEqual(field["remoteRef"]["key"], credential)
        self.assertEqual(cluster["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertNotIn("cnpg.io/skipEmptyWalArchiveCheck", cluster["metadata"]["annotations"])
        self.assertTrue(spec["imageName"].startswith("ghcr.io/cloudnative-pg/postgresql:18.1-system-trixie@sha256:"))

    def test_restore_claim_waits_for_matching_snapshot_and_preserves_source_volume(self):
        claim = self.resource("home-assistant-storage", "PersistentVolumeClaim")
        destination = self.resource("home-assistant-storage", "ReplicationDestination")
        self.assertEqual(claim["spec"]["dataSourceRef"], {
            "apiGroup": "volsync.backube", "kind": "ReplicationDestination",
            "name": destination["metadata"]["name"],
        })
        self.assertEqual(claim["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertEqual(destination["spec"]["restic"]["capacity"], "5Gi")
        self.assertFalse(destination["spec"]["restic"]["cleanupTempPVC"])
        preflight = self.owners["home-assistant-restore-preflight"]["spec"]["postBuild"]["substitute"]
        self.assertEqual(destination["spec"]["trigger"]["manual"], preflight["VOLSYNC_RESTORE_ID"])
        checks = self.owners["home-assistant-storage"]["spec"]["healthCheckExprs"]
        self.assertTrue(any(check["kind"] == "PersistentVolumeClaim"
                            and destination["metadata"]["name"] in check["current"]
                            and "'Bound'" in check["current"] for check in checks))
        self.assertTrue(any(check["kind"] == "ReplicationDestination"
                            and "status.lastManualSync == spec.trigger.manual" in check["current"]
                            and "status.latestImage.name" in check["current"] for check in checks))

    def test_restore_capacity_tracks_claim_expansion(self):
        _, resources = render(config_capacity="10Gi")
        destination = next(resource for resource in resources["home-assistant-storage"]
                           if resource["kind"] == "ReplicationDestination")
        self.assertEqual(destination["spec"]["restic"]["capacity"], "10Gi")

    def test_backup_stays_suspended_and_uses_separate_apollo_repository(self):
        self.assertTrue(self.owners["home-assistant-backup"]["spec"]["suspend"])
        source = self.resource("home-assistant-backup", "ReplicationSource")
        self.assertEqual(source["spec"]["sourcePVC"], "home-assistant-config")
        secret = self.resource("home-assistant-backup", "ExternalSecret", source["spec"]["restic"]["repository"])
        self.assertTrue(secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-apollo-volsync/home-assistant-config"))
        fields = {field["secretKey"]: field["remoteRef"]["key"] for field in secret["spec"]["data"]}
        self.assertEqual(fields["RESTIC_PASSWORD"], "home-assistant-config")
        for field in ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]:
            self.assertEqual(fields[field], "volsync-r2")
        restore = self.resource("home-assistant-restore-preflight", "ExternalSecret")
        self.assertTrue(restore["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-volsync/home-assistant-config"))
        restore_fields = {field["secretKey"]: field["remoteRef"]["key"] for field in restore["spec"]["data"]}
        for field in ["RESTIC_PASSWORD", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]:
            self.assertEqual(restore_fields[field], "home-assistant-migration")

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
        self.assertEqual(ingress["spec"]["defaultBackend"]["service"]["name"], "home-assistant")
        required = {
            "home-assistant-storage": {"home-assistant-restore-preflight", "longhorn-config", "volsync"},
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
