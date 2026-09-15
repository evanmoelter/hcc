import json
from pathlib import Path
import subprocess
import tempfile
import unittest


APP = Path(__file__).resolve().parents[1] / "kubernetes/apollo/apps/database/cnpg-smoke"


def documents(data):
    return json.loads(subprocess.check_output(["yq", "-o=json", "ea", "[.]"], input=data))


class CnpgRehearsalTest(unittest.TestCase):
    def test_flux_preserves_sql_with_substitution_enabled(self):
        for directory in sorted({path.parent for path in APP.glob("*/*.sql")}):
            with self.subTest(stage=directory.name), tempfile.TemporaryDirectory() as temporary:
                owner = documents((APP / f"ks-{directory.name}.yaml").read_bytes())[0]
                owner["spec"]["postBuild"] = {"substitute": {"REHEARSAL_TEST": "enabled"}}
                owner_path = Path(temporary) / "owner.json"
                owner_path.write_text(json.dumps(owner))
                rendered = subprocess.check_output([
                    "flux", "build", "kustomization", owner["metadata"]["name"],
                    "--dry-run", "--strict-substitute", "--path", str(directory),
                    "--kustomization-file", str(owner_path),
                ])
                config = next(item for item in documents(rendered) if item["kind"] == "ConfigMap")
                for sql in directory.glob("*.sql"):
                    self.assertEqual(config["data"][sql.name], sql.read_text(), sql.name)


if __name__ == "__main__":
    unittest.main()
