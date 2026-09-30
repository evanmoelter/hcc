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
    with tempfile.TemporaryDirectory(prefix="authentik-migration-") as directory:
        root = Path(directory)
        for path in ["apps/security", "components/postgres"]:
            shutil.copytree(ROOT / APOLLO / path, root / APOLLO / path)
        parent = documents((ROOT / APOLLO / "flux/apps.yaml").read_bytes())[0]
        parent["spec"]["postBuild"] = {"substitute": {"TEST_RENDER": "true"}}
        owners = {
            resource["metadata"]["name"]: resource
            for resource in build(root, parent, APOLLO / "apps/security")
            if resource["kind"] == "Kustomization"
        }
        resources = {}
        for name in ["authentik-database", "authentik", "webfinger"]:
            owner = owners[name]
            owner["spec"]["postBuild"].setdefault("substitute", {}).update({
                "SECRET_DOMAIN": "example.invalid", "TIMEZONE": "Etc/UTC",
            })
            resources[name] = build(root, owner, owner["spec"]["path"])
        return owners, resources


class AuthentikMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owners, cls.resources = render()

    def resource(self, owner, kind):
        return next(resource for resource in self.resources[owner] if resource["kind"] == kind)

    def test_database_recovers_from_its_apollo_archive(self):
        cluster = self.resource("authentik-database", "Cluster")
        spec = cluster["spec"]
        self.assertEqual(set(spec["bootstrap"]), {"recovery"})
        recovery = spec["bootstrap"]["recovery"]
        self.assertEqual((recovery["database"], recovery["owner"]), ("authentik", "authentik"))
        self.assertEqual(len(spec["externalClusters"]), 1)
        source = next(source for source in spec["externalClusters"]
                      if source["name"] == recovery["source"])
        writer = next(plugin for plugin in spec["plugins"] if plugin.get("isWALArchiver"))
        self.assertEqual(source["plugin"]["name"], "barman-cloud.cloudnative-pg.io")
        self.assertEqual(source["plugin"]["parameters"], writer["parameters"])
        self.assertEqual(writer["parameters"], {
            "barmanObjectName": "authentik-pg", "serverName": "authentik-pg-apollo-v1",
        })
        self.assertEqual(cluster["metadata"]["annotations"]["cnpg.io/skipEmptyWalArchiveCheck"], "enabled")
        self.assertEqual(cluster["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/prune"], "disabled")
        self.assertTrue(spec["imageName"].split(":", 1)[1].startswith("18."))
        store = self.resource("authentik-database", "ObjectStore")
        self.assertEqual(store["spec"]["configuration"]["destinationPath"],
                         "s3://tf-hcc-apollo-cnpg/authentik/")
        self.assertEqual(spec["storage"]["size"], "10Gi")
        self.assertEqual(spec["postgresql"]["parameters"]["max_connections"], "200")

    def test_cleanup_removes_source_configuration_and_credentials(self):
        rendered = json.dumps(self.resources)
        for retired in ["authentik-postgres-migration", "authentik-main", "192.168.6.21"]:
            with self.subTest(retired=retired):
                self.assertNotIn(retired, rendered)
        secret = self.resource("authentik-database", "ExternalSecret")
        self.assertEqual(secret["metadata"]["name"], "authentik-pg-r2")
        remote = {entry["secretKey"]: entry["remoteRef"]["key"] for entry in secret["spec"]["data"]}
        self.assertEqual(remote["R2_ACCESS_KEY_ID"], "cnpg-r2")
        self.assertEqual(remote["R2_SECRET_ACCESS_KEY"], "cnpg-r2")

    def test_application_waits_for_database_and_uses_its_credentials(self):
        deps = {entry["name"] for entry in self.owners["authentik"]["spec"]["dependsOn"]}
        self.assertIn("authentik-database", deps)
        database = self.owners["authentik-database"]["spec"]
        self.assertTrue(database["wait"])
        self.assertTrue(any(check["kind"] == "Cluster" for check in database["healthCheckExprs"]))
        release = self.resource("authentik", "HelmRelease")
        values = release["spec"]["values"]
        for entry in values["global"]["env"]:
            if entry["name"] in {"AUTHENTIK_POSTGRESQL__USER", "AUTHENTIK_POSTGRESQL__PASSWORD"}:
                self.assertEqual(entry["valueFrom"]["secretKeyRef"]["name"], "authentik-pg-app")
        self.assertNotIn("redis", values["authentik"])
        self.assertFalse(values["postgresql"]["enabled"])
        self.assertEqual(release["spec"]["upgrade"]["strategy"]["name"], "RetryOnFailure")
        self.assertFalse(any(resource["kind"] == "PersistentVolumeClaim"
                             for resource in self.resources["authentik"]))

    def test_proxy_headers_are_normalized_on_both_paths(self):
        values = self.resource("authentik", "HelmRelease")["spec"]["values"]
        self.assertEqual(values["authentik"]["listen"]["trusted_proxy_cidrs"],
                         "10.42.0.0/16,127.0.0.1/32,::1/128")
        for name in ["internal", "external"]:
            route = values["server"]["route"][name]
            self.assertEqual(route["parentRefs"][0]["name"], f"envoy-{name}")
            self.assertEqual(route["parentRefs"][0]["sectionName"], "https")
            headers = route["filters"][0]["requestHeaderModifier"]
            configured = {header["name"]: header["value"] for header in headers["set"]}
            self.assertEqual(configured["X-Forwarded-For"], "%DOWNSTREAM_REMOTE_ADDRESS_WITHOUT_PORT%")
            self.assertEqual(configured["X-Forwarded-Host"], "sso.example.invalid")
            self.assertEqual(configured["X-Forwarded-Proto"], "https")
            self.assertIn("Forwarded", headers["remove"])
            self.assertLessEqual({"SSL-Client-Cert", "X-Forwarded-TLS-Client-Cert", "X-Forwarded-Client-Cert"},
                                 set(headers["remove"]))
        policy = self.resource("authentik", "NetworkPolicy")["spec"]
        clients = policy["ingress"][0]["from"]
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"], "network")
        self.assertEqual(set(clients[0]["podSelector"]["matchExpressions"][0]["values"]),
                         {"envoy-internal", "envoy-external"})
        self.assertFalse(self.resource("authentik", "ServiceAccount")["automountServiceAccountToken"])
        self.assertFalse(values["serviceAccount"]["create"])

    def test_webfinger_keeps_root_discovery_and_tunnel_match(self):
        values = self.resource("webfinger", "HelmRelease")["spec"]["values"]
        for name in ["internal", "external"]:
            route = values["route"][name]
            self.assertEqual(route["hostnames"], ["example.invalid"])
            self.assertEqual(route["rules"][0]["matches"][0]["path"], {
                "type": "Exact", "value": "/.well-known/webfinger",
            })
        env = values["controllers"]["webfinger"]["containers"]["app"]["env"]
        self.assertEqual(env["AK_HOST"], "sso.example.invalid")
        cloudflared = documents((ROOT / APOLLO / "apps/network/cloudflared/app/helmrelease.yaml").read_bytes())[0]
        config = cloudflared["spec"]["values"]["configMaps"]["config"]["data"]["config.yaml"]
        ingress = documents(config.encode())[0]["ingress"]
        self.assertTrue(any(rule.get("hostname") == "${SECRET_DOMAIN}"
                            and rule.get("service") == "https://envoy-external.network.svc.cluster.local:443"
                            for rule in ingress))


if __name__ == "__main__":
    unittest.main()
