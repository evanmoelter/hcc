import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APOLLO = Path("kubernetes/apollo")
PAPERLESS = APOLLO / "apps/default/paperless"


def documents(data):
    output = subprocess.check_output(["yq", "-o=json", "ea", "[.]"], input=data)
    return [resource for resource in json.loads(output) if resource is not None]


def build(root, owner):
    owner_file = root / "owner.json"
    owner_file.write_text(json.dumps(owner))
    return documents(subprocess.check_output([
        "flux", "build", "kustomization", owner["metadata"]["name"], "--dry-run",
        "--strict-substitute", "--path", str(root / owner["spec"]["path"]),
        "--kustomization-file", str(owner_file),
    ]))


def render(library_capacity=None):
    with tempfile.TemporaryDirectory(prefix="paperless-migration-") as directory:
        root = Path(directory)
        for path in ["apps/default/paperless", "components/postgres", "components/volsync"]:
            shutil.copytree(ROOT / APOLLO / path, root / APOLLO / path)
        if library_capacity:
            pvc_file = root / PAPERLESS / "storage/pvc.yaml"
            claims = documents(pvc_file.read_bytes())
            for claim in claims:
                if claim["metadata"]["name"] == "paperless-library":
                    claim["spec"]["resources"]["requests"]["storage"] = library_capacity
            pvc_file.write_text("\n---\n".join(json.dumps(claim) for claim in claims))
        owners = {
            resource["metadata"]["name"]: resource
            for filename in ["ks-storage.yaml", "ks-database.yaml", "ks.yaml", "ks-broker.yaml",
                             "ks-sftp.yaml", "ks-tailscale.yaml", "ks-consume-monitor.yaml"]
            for resource in documents((root / PAPERLESS / filename).read_bytes())
        }
        for owner in owners.values():
            owner["spec"].setdefault("postBuild", {}).setdefault("substitute", {}).update({
                "SECRET_DOMAIN": "example.invalid", "SECRET_TAILSCALE_DOMAIN": "example.ts.net",
                "TIMEZONE": "Etc/UTC",
            })
        resources = {name: build(root, owner) for name, owner in owners.items()}
        return owners, resources


class PaperlessMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owners, cls.resources = render()

    def resource(self, owner, kind, name=None):
        return next(resource for resource in self.resources[owner]
                    if resource["kind"] == kind
                    and (name is None or resource["metadata"]["name"] == name))

    def test_database_recovers_from_its_apollo_archive(self):
        cluster = self.resource("paperless-database", "Cluster")
        spec = cluster["spec"]
        self.assertEqual(set(spec["bootstrap"]), {"recovery"})
        recovery = spec["bootstrap"]["recovery"]
        self.assertEqual((recovery["database"], recovery["owner"]), ("paperless", "paperless"))
        self.assertEqual(len(spec["externalClusters"]), 1)
        source = spec["externalClusters"][0]
        self.assertEqual(source["name"], recovery["source"])
        writer = next(plugin for plugin in spec["plugins"] if plugin.get("isWALArchiver"))
        self.assertEqual(source["plugin"]["name"], writer["name"])
        self.assertEqual(source["plugin"]["parameters"], writer["parameters"])
        self.assertFalse(spec["enableSuperuserAccess"])
        annotations = cluster["metadata"]["annotations"]
        self.assertEqual(annotations["cnpg.io/skipEmptyWalArchiveCheck"], "enabled")
        self.assertEqual(annotations["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertEqual(spec["storage"]["size"], "5Gi")

    def test_cleanup_removes_temporary_resources_and_source_credentials(self):
        self.assertNotIn("paperless-restore-preflight", self.owners)
        resources = [resource for group in self.resources.values() for resource in group]
        self.assertFalse(any(resource["kind"] in {"ReplicationDestination", "Job"}
                             for resource in resources))
        rendered = json.dumps(resources)
        for retired in ["paperless-postgres-migration", "paperless-main", "192.168.6.21",
                        "paperless-library-migration", "tf-hcc-volsync",
                        "paperless-library-volsync-restore-migration-20260930"]:
            with self.subTest(retired=retired):
                self.assertNotIn(retired, rendered)
        storage = self.owners["paperless-storage"]["spec"]
        self.assertNotIn("components", storage)
        self.assertNotIn("VOLSYNC_RESTORE_ID", storage.get("postBuild", {}).get("substitute", {}))

    def test_database_archives_to_its_independent_apollo_store(self):
        cluster = self.resource("paperless-database", "Cluster")
        writer = next(plugin for plugin in cluster["spec"]["plugins"] if plugin.get("isWALArchiver"))
        store = self.resource("paperless-database", "ObjectStore", writer["parameters"]["barmanObjectName"])
        self.assertEqual(writer["parameters"]["serverName"], "paperless-pg-apollo-v1")
        self.assertEqual(store["spec"]["configuration"]["destinationPath"],
                         "s3://tf-hcc-apollo-cnpg/paperless/")
        access = store["spec"]["configuration"]["s3Credentials"]["accessKeyId"]
        secret = self.resource("paperless-database", "ExternalSecret", access["name"])
        entry = next(entry for entry in secret["spec"]["data"] if entry["secretKey"] == access["key"])
        self.assertEqual(entry["remoteRef"]["key"], "cnpg-r2")
        backup = self.resource("paperless-database", "ScheduledBackup")
        self.assertEqual(backup["spec"]["cluster"]["name"], cluster["metadata"]["name"])
        self.assertEqual(backup["spec"]["pluginConfiguration"]["name"], writer["name"])

    def test_cleanup_preserves_bound_claims_and_storage_health_checks(self):
        library = self.resource("paperless-storage", "PersistentVolumeClaim", "paperless-library")
        consume = self.resource("paperless-storage", "PersistentVolumeClaim", "paperless-consume")
        self.assertEqual(library["spec"]["dataSourceRef"], {
            "apiGroup": "volsync.backube", "kind": "ReplicationDestination",
            "name": "paperless-library-bootstrap-migration-20260930",
        })
        self.assertEqual(library["spec"]["resources"]["requests"]["storage"], "50Gi")
        self.assertEqual(library["spec"]["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(consume["spec"]["resources"]["requests"]["storage"], "1Gi")
        self.assertEqual(consume["spec"]["accessModes"], ["ReadWriteMany"])
        self.assertNotIn("dataSourceRef", consume["spec"])
        for claim in [library, consume]:
            self.assertEqual(claim["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertEqual({resource["kind"] for resource in self.resources["paperless-storage"]},
                         {"PersistentVolumeClaim"})
        storage = self.owners["paperless-storage"]["spec"]
        self.assertEqual(storage["path"], "./kubernetes/apollo/apps/default/paperless/storage")
        self.assertEqual(storage["targetNamespace"], "default")
        self.assertEqual(storage["healthCheckExprs"], [{
            "apiVersion": "v1", "kind": "PersistentVolumeClaim",
            "current": "has(status.phase) && status.phase == 'Bound'",
        }])

    def test_expanding_library_does_not_reintroduce_restore_resources(self):
        _, resources = render(library_capacity="75Gi")
        storage = resources["paperless-storage"]
        self.assertEqual(len(storage), 2)
        self.assertTrue(all(resource["kind"] == "PersistentVolumeClaim" for resource in storage))
        library = next(resource for resource in storage if resource["metadata"]["name"] == "paperless-library")
        self.assertEqual(library["spec"]["resources"]["requests"]["storage"], "75Gi")
        self.assertEqual(library["spec"]["dataSourceRef"]["name"],
                         "paperless-library-bootstrap-migration-20260930")

    def test_backup_uses_apollo_credentials_and_repository(self):
        self.assertFalse(self.owners["paperless-library-backup"]["spec"].get("suspend", False))
        source = self.resource("paperless-library-backup", "ReplicationSource")
        secret = self.resource("paperless-library-backup", "ExternalSecret",
                               source["spec"]["restic"]["repository"])
        self.assertEqual(source["spec"]["sourcePVC"], "paperless-library")
        self.assertTrue(secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-apollo-volsync/paperless-library"))
        fields = {entry["secretKey"]: entry["remoteRef"]["key"] for entry in secret["spec"]["data"]}
        self.assertEqual(fields["RESTIC_PASSWORD"], "paperless-library")
        for field in ["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]:
            self.assertEqual(fields[field], "volsync-r2")
        security = source["spec"]["restic"]["moverSecurityContext"]
        self.assertEqual((security["runAsUser"], security["runAsGroup"], security["fsGroup"]),
                         (1000, 1000, 1000))

    def test_consume_backup_is_separate_and_short_lived(self):
        source = self.resource("paperless-consume-backup", "ReplicationSource")
        library = self.resource("paperless-library-backup", "ReplicationSource")
        self.assertEqual(source["spec"]["sourcePVC"], "paperless-consume")
        self.assertEqual(source["spec"]["trigger"], {"schedule": "15 * * * *"})
        mover = source["spec"]["restic"]
        self.assertEqual(mover["retain"], {"within": "7d"})
        self.assertEqual(mover["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(mover["copyMethod"], "Snapshot")
        self.assertNotEqual(mover["repository"], library["spec"]["restic"]["repository"])
        secret = self.resource("paperless-consume-backup", "ExternalSecret", mover["repository"])
        self.assertTrue(secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-apollo-volsync/paperless-consume"))
        password = next(entry for entry in secret["spec"]["data"] if entry["secretKey"] == "RESTIC_PASSWORD")
        self.assertEqual(password["remoteRef"]["key"], "paperless-consume")
        self.assertEqual(library["spec"]["restic"]["retain"], {"daily": 7, "weekly": 4, "monthly": 12})

    def test_consume_monitor_can_observe_when_paperless_is_down(self):
        owner = self.owners["paperless-consume-monitor"]["spec"]
        self.assertNotIn("paperless", {dependency["name"] for dependency in owner["dependsOn"]})
        values = self.resource("paperless-consume-monitor", "HelmRelease")["spec"]["values"]
        self.assertEqual(set(values["persistence"]), {"config", "consume"})
        mounts = values["persistence"]["consume"]["advancedMounts"]["monitor"]
        self.assertTrue(mounts["app"][0]["readOnly"])
        self.assertFalse(mounts["seed-backup"][0].get("readOnly", False))
        self.assertNotIn("envFrom", values["controllers"]["monitor"]["containers"]["app"])

    def test_dependencies_preserve_storage_database_and_backup_order(self):
        required = {
            "paperless-storage": {"longhorn-config"},
            "paperless-database": {"plugin-barman-cloud", "longhorn-config", "onepassword-store"},
            "paperless-library-backup": {"paperless", "volsync", "onepassword-store"},
            "paperless-consume-backup": {"paperless-consume-monitor", "volsync", "onepassword-store"},
            "paperless-consume-monitor": {"paperless-storage"},
            "paperless": {"paperless-storage", "paperless-database", "paperless-broker", "authentik"},
            "paperless-sftp": {"paperless", "paperless-storage", "onepassword-store"},
            "paperless-tailscale": {"paperless", "tailscale-config"},
            "paperless-broker": {"dragonfly-operator", "onepassword-store"},
        }
        graph = {name: {dependency["name"] for dependency in owner["spec"]["dependsOn"]}
                 for name, owner in self.owners.items()}
        for name, dependencies in required.items():
            self.assertLessEqual(dependencies, graph[name])
            self.assertTrue(self.owners[name]["spec"]["wait"])
        pending = set(graph)
        while pending:
            ready = {name for name in pending if not graph[name] & pending}
            self.assertTrue(ready, f"Dependency cycle: {pending}")
            pending -= ready
        database_checks = self.owners["paperless-database"]["spec"]["healthCheckExprs"]
        self.assertTrue(any(check["kind"] == "Cluster" and "e.status == 'True'" in check["current"]
                            for check in database_checks))

    def test_application_uses_imported_data_and_preserves_private_access(self):
        release = self.resource("paperless", "HelmRelease")
        self.assertEqual(release["spec"]["upgrade"]["strategy"]["name"], "RetryOnFailure")
        values = release["spec"]["values"]
        controller = values["controllers"]["paperless"]
        self.assertEqual(controller["replicas"], 1)
        self.assertEqual(controller["strategy"], "Recreate")
        app = controller["containers"]["app"]
        env = app["env"]
        self.assertEqual(env["PAPERLESS_DBSSLMODE"], "verify-full")
        for key in ["PAPERLESS_DBUSER", "PAPERLESS_DBPASS"]:
            self.assertEqual(env[key]["valueFrom"]["secretKeyRef"]["name"], "paperless-pg-app")
        for identifier in ["library", "consume"]:
            self.assertEqual(values["persistence"][identifier]["existingClaim"], f"paperless-{identifier}")
        mover = self.resource("paperless-library-backup", "ReplicationSource")["spec"]["restic"]
        self.assertEqual(controller["pod"]["securityContext"]["runAsUser"],
                         mover["moverSecurityContext"]["runAsUser"])
        self.assertEqual(set(values["route"]), {"internal"})
        self.assertEqual(values["route"]["internal"]["parentRefs"][0]["name"], "envoy-internal")
        ingress = self.resource("paperless-tailscale", "Ingress")
        self.assertEqual(ingress["spec"]["ingressClassName"], "tailscale")
        self.assertEqual(ingress["spec"]["defaultBackend"]["service"]["name"], "paperless")
        self.assertEqual(ingress["spec"]["tls"][0]["hosts"], ["paperless"])

    def test_broker_and_application_share_only_their_new_password(self):
        broker = self.resource("paperless-broker", "Dragonfly")
        password_ref = broker["spec"]["authentication"]["passwordFromSecret"]
        secret = self.resource("paperless-broker", "ExternalSecret", password_ref["name"])
        password = next(field["remoteRef"] for field in secret["spec"]["data"]
                        if field["secretKey"] == password_ref["key"])
        app_secret = self.resource("paperless", "ExternalSecret")
        self.assertIn(password, [field["remoteRef"] for field in app_secret["spec"]["data"]])
        redis_url = app_secret["spec"]["target"]["template"]["data"]["PAPERLESS_REDIS"]
        self.assertIn(f'@{broker["metadata"]["name"]}.default.svc.cluster.local:6379/', redis_url)
        self.assertNotIn("snapshot", broker["spec"])
        account = self.resource("paperless-broker", "ServiceAccount", broker["spec"]["serviceAccountName"])
        self.assertFalse(account["automountServiceAccountToken"])


if __name__ == "__main__":
    unittest.main()
