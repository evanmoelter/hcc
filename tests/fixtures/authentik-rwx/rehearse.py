import argparse
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
NAMESPACE = "authentik-rwx-proof"
SNAPSHOT_CLASS = "longhorn-snapclass"


def resource(kind, name, spec, api="v1"):
    return {"apiVersion": api, "kind": kind,
            "metadata": {"name": name, "namespace": NAMESPACE}, "spec": spec}


def claim(name, mode, snapshot=None):
    spec = {"accessModes": [mode], "storageClassName": "longhorn",
            "resources": {"requests": {"storage": "1Gi"}}}
    if snapshot:
        spec["dataSourceRef"] = {"apiGroup": "snapshot.storage.k8s.io",
                                 "kind": "VolumeSnapshot", "name": snapshot}
    return resource("PersistentVolumeClaim", name, spec)


def snapshot(name, source):
    return resource("VolumeSnapshot", name, {
        "volumeSnapshotClassName": SNAPSHOT_CLASS,
        "source": {"persistentVolumeClaimName": source},
    }, "snapshot.storage.k8s.io/v1")


def pod(name, pvc, node, image, required):
    checks = [f"test \"$(cat /data/{item})\" = {item}" for item in required]
    checks += [f"printf '%s' {name} > /data/{name}", "touch /data/.volsync-seed", "sleep 3600"]
    return resource("Pod", name, {
        "nodeSelector": {"kubernetes.io/hostname": node},
        "restartPolicy": "Never", "automountServiceAccountToken": False,
        "securityContext": {"runAsUser": 568, "runAsGroup": 568, "runAsNonRoot": True,
                            "fsGroup": 568, "fsGroupChangePolicy": "OnRootMismatch",
                            "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{
            "name": "proof", "image": image,
            "command": ["sh", "-ec", "; ".join(["umask 077"] + checks)],
            "securityContext": {"allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
            "resources": {"requests": {"cpu": "10m", "memory": "16Mi"}, "limits": {"memory": "64Mi"}},
            "volumeMounts": [{"name": "data", "mountPath": "/data"}],
            "readinessProbe": {"exec": {"command": ["sh", "-ec", f"test -f /data/{name}"]},
                               "periodSeconds": 2},
        }],
        "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": pvc}}],
    })


def main():
    parser = argparse.ArgumentParser(description="Render an isolated RWX rehearsal; --run changes cluster state.")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--context")
    args = parser.parse_args()
    if args.run and args.context != "apollo":
        parser.error("--run requires --context apollo and explicit operator approval")
    image = json.loads(subprocess.check_output([
        "yq", "-o=json", ".spec.values.global.image",
        str(ROOT / "kubernetes/apollo/apps/security/authentik/app/helmrelease.yaml"),
    ]))
    image = f"{image['repository']}:{image['tag']}@{image['digest']}"
    namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {
        "name": NAMESPACE, "labels": {"pod-security.kubernetes.io/enforce": "restricted"}}}
    stages = [
        claim("source", "ReadWriteMany"),
        pod("source-a", "source", "hcc5", image, []),
        pod("source-b", "source", "hcc6", image, ["source-a"]),
        snapshot("source-snapshot", "source"),
        claim("backup-clone", "ReadWriteOnce", "source-snapshot"),
        pod("backup-reader", "backup-clone", "hcc5", image, ["source-a", "source-b"]),
        snapshot("restore-snapshot", "backup-clone"),
        claim("restored", "ReadWriteMany", "restore-snapshot"),
        pod("restored-a", "restored", "hcc5", image, ["source-a", "source-b", "backup-reader"]),
        pod("restored-b", "restored", "hcc6", image, ["restored-a"]),
    ]
    if not args.run:
        print(json.dumps({"apiVersion": "v1", "kind": "List", "items": [namespace] + stages}, indent=2))
        return

    def kubectl(*arguments, data=None):
        return subprocess.check_output(["kubectl", "--context", args.context, *arguments],
                                       input=data, text=True)

    snapshot_class = json.loads(kubectl("get", "volumesnapshotclass", SNAPSHOT_CLASS, "-o", "json"))
    if snapshot_class["deletionPolicy"] != "Delete":
        raise RuntimeError("Rehearsal requires snapshot deletionPolicy Delete for isolated cleanup")
    kubectl("create", "-f", "-", data=json.dumps(namespace))
    try:
        for obj in stages:
            target = f"{obj['kind']}/{obj['metadata']['name']}"
            print(f"Creating and checking {target}", flush=True)
            kubectl("create", "-f", "-", data=json.dumps(obj))
            condition = {"Pod": "condition=Ready", "PersistentVolumeClaim": "jsonpath={.status.phase}=Bound",
                         "VolumeSnapshot": "jsonpath={.status.readyToUse}=true"}[obj["kind"]]
            kubectl("-n", NAMESPACE, "wait", target, f"--for={condition}", "--timeout=5m")
        print("PASS: cross-node UID 568 writes, RWX → RWO clone, and RWO → RWX restore", flush=True)
        kubectl("delete", "namespace", NAMESPACE, "--wait=true", "--timeout=5m")
        print("Disposable namespace removed", flush=True)
    except Exception:
        print(f"Rehearsal stopped; inspect namespace {NAMESPACE}. No production resources were targeted.", flush=True)
        raise


if __name__ == "__main__":
    main()
