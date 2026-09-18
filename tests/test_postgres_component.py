import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APOLLO = Path("kubernetes/apollo")
APP = APOLLO / "apps/default/postgres-example"
FIXTURE = ROOT / "tests/fixtures/postgres"
PLUGIN = "barman-cloud.cloudnative-pg.io"


def command(*args, data=None):
    return subprocess.check_output(args, input=data)


def documents(data):
    return [d for d in json.loads(command("yq", "-o=json", "ea", "[.]", data=data)) if d is not None]


def read(path):
    return documents(path.read_bytes())[0]


def write(path, value):
    path.write_text(json.dumps(value))


def render(mode="recovery", substitutions=None):
    with tempfile.TemporaryDirectory(prefix="postgres-component-") as directory:
        root = Path(directory)
        shutil.copytree(ROOT / APOLLO / "components/postgres", root / APOLLO / "components/postgres")
        shutil.copytree(FIXTURE, root / APP)
        owner_path = root / APP / "ks-database.yaml"
        owner = read(owner_path)
        owner["spec"]["postBuild"]["substitute"].update(substitutions or {})
        if mode == "init":
            owner["spec"]["components"].append("../../../../components/postgres/init")
        write(owner_path, owner)
        config_path = root / APP / "database/kustomization.yaml"
        config = read(config_path)
        if mode == "migration":
            source = read(root / APOLLO / "components/postgres/objectstore.yaml")
            source["metadata"]["name"] = "${APP}-pg-source"
            del source["spec"]["retentionPolicy"]
            source["spec"]["configuration"]["destinationPath"] = "s3://tf-hcc-cloudnativepg/"
            for credential in source["spec"]["configuration"]["s3Credentials"].values():
                credential["name"] = "${APP}-pg-source-r2"
            source["spec"].pop("instanceSidecarConfiguration")
            write(root / APP / "database/source.yaml", source)
            config["resources"] = ["source.yaml"]
            external = [{"name": "${APP}-pg-backup", "plugin": {
                "name": PLUGIN,
                "parameters": {"barmanObjectName": "${APP}-pg-source", "serverName": "mealie-pg-v1"},
            }}]
            patches = [{"op": "replace", "path": "/spec/externalClusters", "value": external}]
        elif mode == "import":
            patches = [
                {"op": "replace", "path": "/spec/bootstrap", "value": {"initdb": {
                    "database": "example", "owner": "example", "import": {
                        "type": "microservice", "databases": ["example"],
                        "source": {"externalCluster": "cnpg-cluster-source"},
                    },
                }}},
                {"op": "replace", "path": "/spec/externalClusters", "value": [{
                    "name": "cnpg-cluster-source",
                    "connectionParameters": {"host": "192.0.2.21", "user": "postgres", "dbname": "example"},
                    "password": {"name": "postgres-example-import", "key": "password"},
                }]},
                {"op": "remove", "path": "/metadata/annotations/cnpg.io~1skipEmptyWalArchiveCheck"},
            ]
        else:
            patches = []
        if patches:
            config["patches"] = [{"target": {"group": "postgresql.cnpg.io", "kind": "Cluster"},
                                  "patch": json.dumps(patches)}]
        write(config_path, config)
        write(root / APOLLO / "apps/kustomization.yaml", {
            "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": ["default/postgres-example/ks-database.yaml", "default/postgres-example/ks.yaml"],
        })
        (root / APOLLO / "flux").mkdir()
        parent = read(ROOT / APOLLO / "flux/apps.yaml")
        write(root / APOLLO / "flux/apps.yaml", parent)
        bootstrap = next(r for r in documents((ROOT / APOLLO / "flux/config/cluster.yaml").read_bytes())
                         if r["kind"] == "Kustomization")
        bootstrap["spec"]["postBuild"]["substitute"] = {"TEST_RENDER": "true"}
        write(root / "bootstrap.yaml", bootstrap)
        parent = documents(command(
            "flux", "build", "kustomization", "cluster", "--dry-run",
            "--path", str(root / APOLLO / "flux"), "--kustomization-file", str(root / "bootstrap.yaml"),
        ))[0]
        parent["spec"]["postBuild"]["substitute"] = {"TEST_RENDER": "true"}
        write(root / "parent.yaml", parent)
        owners = documents(command(
            "flux", "build", "kustomization", "cluster-apps", "--dry-run",
            "--path", str(root / APOLLO / "apps"), "--kustomization-file", str(root / "parent.yaml"),
        ))
        database = next(o for o in owners if o["metadata"]["name"] == "postgres-example-cluster")
        write(owner_path, database)
        resources = documents(command(
            "flux", "build", "kustomization", "postgres-example-cluster", "--dry-run", "--strict-substitute",
            "--path", str(root / APP / "database"), "--kustomization-file", str(owner_path),
        ))
        for resource in resources:
            annotations = resource["metadata"].get("annotations", {})
            annotations.pop("config.kubernetes.io/origin", None)
            if not annotations:
                resource["metadata"].pop("annotations", None)
        return owners, resources


class PostgresComponentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.states = {mode: render(mode) for mode in ["recovery", "init", "migration", "import"]}

    def resource(self, mode, kind, name=None):
        return next(r for r in self.states[mode][1]
                    if r["kind"] == kind and (name is None or r["metadata"]["name"] == name))

    def test_rendered_resources_match_schemas(self):
        resources = [r for owners, rendered in self.states.values() for r in owners + rendered]
        command(
            "kubeconform", "-strict", "-schema-location", "default", "-schema-location",
            "https://k8s-schemas.home-operations.com/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json",
            data="\n---\n".join(json.dumps(r) for r in resources).encode(),
        )

    def test_rebuild_requires_recovery_from_its_own_archive(self):
        cluster = self.resource("recovery", "Cluster")
        self.assertEqual(set(cluster["spec"]["bootstrap"]), {"recovery"})
        external = cluster["spec"]["externalClusters"][0]
        self.assertEqual(cluster["spec"]["bootstrap"]["recovery"]["source"], external["name"])
        self.assertEqual(external["plugin"]["parameters"], cluster["spec"]["plugins"][0]["parameters"])
        self.assertEqual(cluster["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")

    def test_explicit_init_replaces_recovery_and_restores_archive_safety_check(self):
        cluster = self.resource("init", "Cluster")
        self.assertEqual(cluster["spec"]["bootstrap"], {"initdb": {"database": "example", "owner": "example"}})
        self.assertNotIn("externalClusters", cluster["spec"])
        self.assertNotIn("cnpg.io/skipEmptyWalArchiveCheck", cluster["metadata"]["annotations"])

    def test_physical_migration_reads_old_archive_with_separate_credentials(self):
        cluster = self.resource("migration", "Cluster")
        source = self.resource("migration", "ObjectStore", "postgres-example-pg-source")
        writer = self.resource("migration", "ObjectStore", "postgres-example-pg")
        self.assertNotIn("retentionPolicy", source["spec"])
        self.assertNotEqual(source["spec"]["configuration"]["s3Credentials"],
                            writer["spec"]["configuration"]["s3Credentials"])
        self.assertEqual(cluster["spec"]["externalClusters"][0]["plugin"]["parameters"]["serverName"], "mealie-pg-v1")
        self.assertEqual(cluster["spec"]["plugins"][0]["parameters"]["serverName"], "postgres-example-pg-apollo-v1")

    def test_cleanup_preserves_writer_and_switches_future_recovery_to_apollo(self):
        for mode in ["init", "migration", "import"]:
            for kind in ["ObjectStore", "ScheduledBackup", "ExternalSecret"]:
                name = "postgres-example-pg-r2" if kind == "ExternalSecret" else "postgres-example-pg"
                self.assertEqual(self.resource(mode, kind, name), self.resource("recovery", kind, name))
            before = copy.deepcopy(self.resource(mode, "Cluster"))
            after = copy.deepcopy(self.resource("recovery", "Cluster"))
            for cluster in [before, after]:
                cluster["spec"].pop("bootstrap")
                cluster["spec"].pop("externalClusters", None)
                cluster["metadata"]["annotations"].pop("cnpg.io/skipEmptyWalArchiveCheck", None)
            self.assertEqual(before, after)

    def test_logical_import_survives_parent_patches(self):
        bootstrap = self.resource("import", "Cluster")["spec"]["bootstrap"]
        self.assertEqual(set(bootstrap), {"initdb"})
        self.assertEqual(bootstrap["initdb"]["import"]["source"]["externalCluster"], "cnpg-cluster-source")

    def test_backup_endpoint_and_credentials_come_from_eso(self):
        store = self.resource("recovery", "ObjectStore")
        secret = self.resource("recovery", "ExternalSecret")
        refs = {d["secretKey"]: d["remoteRef"]["key"] for d in secret["spec"]["data"]}
        self.assertEqual(refs, {"ACCOUNT_ID": "cloudflare-r2", "R2_ACCESS_KEY_ID": "cnpg-r2",
                                "R2_SECRET_ACCESS_KEY": "cnpg-r2"})
        self.assertNotIn("endpointURL", store["spec"]["configuration"])
        self.assertNotIn("serverName", store["spec"]["configuration"])
        env = store["spec"]["instanceSidecarConfiguration"]["env"][0]
        self.assertEqual(env["name"], "AWS_ENDPOINT_URL_S3")
        self.assertEqual(env["valueFrom"]["secretKeyRef"]["name"], secret["metadata"]["name"])

    def test_application_waits_for_database_and_platform_dependencies(self):
        owners = {r["metadata"]["name"]: r for r in self.states["recovery"][0]}
        self.assertEqual(owners["postgres-example"]["spec"]["dependsOn"], [{"name": "postgres-example-cluster"}])
        database = owners["postgres-example-cluster"]["spec"]
        self.assertTrue(database["wait"])
        self.assertEqual({d["name"] for d in database["dependsOn"]},
                         {"plugin-barman-cloud", "longhorn-config", "onepassword-store"})

    def test_app_overrides_preserve_archive_identity(self):
        _, resources = render(substitutions={
            "POSTGRES_CAPACITY": "10Gi", "POSTGRES_INSTANCES": "3",
            "POSTGRES_RETENTION": "30d", "POSTGRES_BACKUP_SCHEDULE": "0 0 3 * * *",
        })
        cluster = next(r for r in resources if r["kind"] == "Cluster")
        self.assertEqual(cluster["spec"]["storage"]["size"], "10Gi")
        self.assertEqual(cluster["spec"]["instances"], 3)
        self.assertEqual(next(r for r in resources if r["kind"] == "ObjectStore")["spec"]["retentionPolicy"], "30d")
        self.assertEqual(next(r for r in resources if r["kind"] == "ScheduledBackup")["spec"]["schedule"], "0 0 3 * * *")
        self.assertEqual(cluster["spec"]["plugins"], self.resource("recovery", "Cluster")["spec"]["plugins"])


if __name__ == "__main__":
    unittest.main()
