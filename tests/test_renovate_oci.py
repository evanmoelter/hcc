import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXTRACT = """
const fs = require('node:fs');
const vm = require('node:vm');
const config = vm.runInNewContext('(' + fs.readFileSync('.github/renovate.json5', 'utf8') + ')');
const manager = config.customManagers.find(m => m.description.includes('Process OCI dependencies'));
const content = fs.readFileSync(0, 'utf8');
const matches = manager.matchStrings.flatMap(pattern =>
    [...content.matchAll(new RegExp(pattern, 'g'))].map(match => match.groups));
process.stdout.write(JSON.stringify(matches));
"""


class RenovateOciTests(unittest.TestCase):
    def extract(self, content):
        result = subprocess.run(
            ["node", "-e", EXTRACT], cwd=ROOT, input=content,
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    def test_tag_and_digest_are_separate_in_quoted_and_unquoted_values(self):
        digest = "sha256:" + "a" * 64
        for quote in ('"', "'", ""):
            with self.subTest(quote=quote):
                self.assertEqual(self.extract(
                    f'artifact: {quote}oci://ghcr.io/example/bundle:v1.2.3@{digest}{quote}\n'
                ), [{
                    "depName": "ghcr.io/example/bundle",
                    "currentValue": "v1.2.3",
                    "currentDigest": digest,
                }])

    def test_tag_only_and_registry_port(self):
        self.assertEqual(self.extract('artifact: "oci://registry.example:5000/bundle:v1.2.3"'), [{
            "depName": "registry.example:5000/bundle",
            "currentValue": "v1.2.3",
        }])

    def test_untagged_references_do_not_consume_later_yaml_fields(self):
        self.assertEqual(self.extract(
            'url: oci://ghcr.io/example/chart\nref:\n  tag: 1.2.3\n'
            'artifact: "oci://ghcr.io/example/bundle:v1.2.3"\n'
        ), [{"depName": "ghcr.io/example/bundle", "currentValue": "v1.2.3"}])

    def test_invalid_digest_is_not_extracted_as_a_tag_only_reference(self):
        self.assertEqual(self.extract(
            'artifact: "oci://ghcr.io/example/bundle:v1.2.3@sha256:abc"'
        ), [])

    def test_apollo_bundle_is_extracted_once_with_tag_and_digest(self):
        content = (ROOT / "kubernetes/apollo/apps/flux-system/flux-instance/app/fluxinstance.yaml").read_text()
        dependencies = self.extract(content)
        self.assertEqual(len(dependencies), 1)
        dependency = dependencies[0]
        self.assertEqual(dependency["depName"], "ghcr.io/controlplaneio-fluxcd/flux-operator-manifests")
        self.assertRegex(dependency["currentValue"], r"^v\d+\.\d+\.\d+$")
        self.assertRegex(dependency["currentDigest"], r"^sha256:[a-f0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
