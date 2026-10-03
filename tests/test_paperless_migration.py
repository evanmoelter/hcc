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
                             "ks-sftp.yaml", "ks-tailscale.yaml"]
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

    def test_import_selects_only_paperless_and_reassigns_owner(self):
        cluster = self.resource("paperless-database", "Cluster")
        spec = cluster["spec"]
        self.assertEqual(set(spec["bootstrap"]), {"initdb"})
        init = spec["bootstrap"]["initdb"]
        self.assertEqual((init["database"], init["owner"]), ("paperless", "paperless"))
        self.assertEqual(init["import"]["type"], "microservice")
        self.assertEqual(init["import"]["databases"], ["paperless"])
        self.assertNotIn("roles", init["import"])
        self.assertNotIn("secret", init)
        self.assertEqual(len(spec["externalClusters"]), 1)
        source = spec["externalClusters"][0]
        self.assertEqual(source["name"], init["import"]["source"]["externalCluster"])
        self.assertEqual(source["connectionParameters"], {
            "host": "192.168.6.21", "port": "5432", "user": "paperless-db",
            "dbname": "paperless", "sslmode": "require",
        })
        secret = self.resource("paperless-database", "ExternalSecret", source["password"]["name"])
        entry = next(entry for entry in secret["spec"]["data"]
                     if entry["secretKey"] == source["password"]["key"])
        self.assertEqual(entry["remoteRef"], {
            "key": "paperless-postgres-migration", "property": "PAPERLESS_DBPASS",
        })
        self.assertFalse(spec["enableSuperuserAccess"])
        annotations = cluster["metadata"]["annotations"]
        self.assertNotIn("cnpg.io/skipEmptyWalArchiveCheck", annotations)
        self.assertEqual(annotations["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertEqual(spec["storage"]["size"], "5Gi")

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

    def test_library_hydration_preserves_identity_and_protects_both_claims(self):
        library = self.resource("paperless-storage", "PersistentVolumeClaim", "paperless-library")
        consume = self.resource("paperless-storage", "PersistentVolumeClaim", "paperless-consume")
        restore = self.resource("paperless-storage", "ReplicationDestination")
        self.assertEqual(library["spec"]["dataSourceRef"], {
            "apiGroup": "volsync.backube", "kind": "ReplicationDestination",
            "name": restore["metadata"]["name"],
        })
        self.assertEqual(library["spec"]["resources"]["requests"]["storage"], "50Gi")
        self.assertEqual(restore["spec"]["restic"]["capacity"], "50Gi")
        self.assertEqual(library["spec"]["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(consume["spec"]["resources"]["requests"]["storage"], "1Gi")
        self.assertEqual(consume["spec"]["accessModes"], ["ReadWriteMany"])
        self.assertNotIn("dataSourceRef", consume["spec"])
        for claim in [library, consume]:
            self.assertEqual(claim["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertFalse(restore["spec"]["restic"]["cleanupTempPVC"])
        self.assertEqual(restore["spec"]["trigger"], {"manual": "migration-20260930"})
        backup = self.resource("paperless-library-backup", "ReplicationSource")
        for mover in [restore, backup]:
            security = mover["spec"]["restic"]["moverSecurityContext"]
            self.assertEqual((security["runAsUser"], security["runAsGroup"], security["fsGroup"]),
                             (1000, 1000, 1000))
        checks = {check["kind"]: check["current"]
                  for check in self.owners["paperless-storage"]["spec"]["healthCheckExprs"]}
        self.assertIn("status.phase == 'Bound'", checks["PersistentVolumeClaim"])
        self.assertIn(restore["metadata"]["name"], checks["PersistentVolumeClaim"])
        self.assertIn("status.lastManualSync == spec.trigger.manual", checks["ReplicationDestination"])
        self.assertIn("has(status.latestImage.name)", checks["ReplicationDestination"])

    def test_restore_capacity_tracks_the_claim_when_expanded(self):
        _, resources = render(library_capacity="75Gi")
        restore = next(resource for resource in resources["paperless-storage"]
                       if resource["kind"] == "ReplicationDestination")
        self.assertEqual(restore["spec"]["restic"]["capacity"], "75Gi")

    def test_restore_and_backup_have_separate_credentials_and_repositories(self):
        restore = self.resource("paperless-storage", "ReplicationDestination")
        source = self.resource("paperless-library-backup", "ReplicationSource")
        restore_secret = self.resource("paperless-restore-preflight", "ExternalSecret",
                                       restore["spec"]["restic"]["repository"])
        backup_secret = self.resource("paperless-library-backup", "ExternalSecret",
                                      source["spec"]["restic"]["repository"])
        self.assertEqual(source["spec"]["sourcePVC"], "paperless-library")
        self.assertTrue(restore_secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-volsync/paperless-library"))
        self.assertTrue(backup_secret["spec"]["target"]["template"]["data"]["RESTIC_REPOSITORY"].endswith(
            "/tf-hcc-apollo-volsync/paperless-library"))
        restore_fields = {entry["secretKey"]: entry["remoteRef"]["key"]
                          for entry in restore_secret["spec"]["data"]}
        backup_fields = {entry["secretKey"]: entry["remoteRef"]["key"]
                         for entry in backup_secret["spec"]["data"]}
        for field in ["RESTIC_PASSWORD", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]:
            self.assertEqual(restore_fields[field], "paperless-library-migration")
            self.assertNotEqual(restore_fields[field], backup_fields[field])
        self.assertEqual(backup_fields["RESTIC_PASSWORD"], "paperless-library")
        self.assertEqual(backup_fields["R2_ACCESS_KEY_ID"], "volsync-r2")
        job = self.resource("paperless-restore-preflight", "Job")
        credential = job["spec"]["template"]["spec"]["containers"][0]["envFrom"][0]["secretRef"]["name"]
        self.assertEqual(credential, restore_secret["metadata"]["name"])

    def test_dependencies_keep_restore_ahead_of_storage_and_backups_gated(self):
        required = {
            "paperless-restore-preflight": {"onepassword-store"},
            "paperless-storage": {"paperless-restore-preflight", "volsync", "longhorn-config"},
            "paperless-database": {"plugin-barman-cloud", "longhorn-config", "onepassword-store"},
            "paperless-library-backup": {"paperless", "volsync", "onepassword-store"},
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
        self.assertTrue(self.owners["paperless-library-backup"]["spec"]["suspend"])
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
        mover = self.resource("paperless-storage", "ReplicationDestination")["spec"]["restic"]
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
