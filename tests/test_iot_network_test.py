import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "kubernetes/apollo/apps/default/iot-network-test"
SPEC = importlib.util.spec_from_file_location("iot_probe", APP / "app/probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class ProbeTest(unittest.TestCase):
    def test_busybox_address_and_route_output(self):
        address = "3: net1@if7: <BROADCAST,MULTICAST,UP> mtu 1500\n    inet 192.168.6.105/22 scope global net1\n    inet6 fe80::1/64 scope link\n"
        PROBE.check_address(PROBE.parse_ip_output(("address",), address), "192.168.6.105")
        route = "192.168.4.35 dev net1 src 192.168.6.105\n    cache\n"
        PROBE.check_route(PROBE.parse_ip_output(("route",), route), "net1", "192.168.6.105")
        default = "default via 10.42.0.1 dev eth0 \n"
        PROBE.check_route(PROBE.parse_ip_output(("route",), default), "eth0")
        with self.assertRaises(RuntimeError):
            PROBE.check_route(PROBE.parse_ip_output(("route",), default), "net1", "192.168.6.105")
        with self.assertRaises(RuntimeError):
            PROBE.check_route(PROBE.parse_ip_output(("route",), "unreachable 192.168.4.35"), "net1")

    def test_ip_command_does_not_require_iproute2_json_support(self):
        with patch.object(PROBE.subprocess, "check_output", return_value="default dev eth0") as command:
            PROBE.check_route(PROBE.ip_state("route", "show", "default"), "eth0")
        self.assertEqual(command.call_args.args[0], ["ip", "-4", "route", "show", "default"])

    def test_address_requires_correct_source_and_mask(self):
        good = [{"addr_info": [{"local": "192.168.6.105", "prefixlen": 22}]}]
        PROBE.check_address(good, "192.168.6.105")
        with self.assertRaises(RuntimeError):
            PROBE.check_address(good, "192.168.6.106")
        with self.assertRaises(RuntimeError):
            PROBE.check_address([{"addr_info": [{"local": "192.168.6.105", "prefixlen": 24}]}],
                                "192.168.6.105")

    def test_routes_reject_wrong_interface_or_source(self):
        PROBE.check_route([{"dev": "net1", "prefsrc": "192.168.6.105"}], "net1", "192.168.6.105")
        for route in [[], [{"dev": "eth0", "prefsrc": "192.168.6.105"}],
                      [{"dev": "net1", "prefsrc": "10.42.0.1"}]]:
            with self.assertRaises(RuntimeError):
                PROBE.check_route(route, "net1", "192.168.6.105")
        with self.assertRaises(RuntimeError):
            PROBE.check_route([{"dev": "eth0"}, {"dev": "net1"}], "eth0")

    def test_gateway_ping_uses_unprivileged_source_binding(self):
        with patch.object(PROBE.subprocess, "run", return_value=Mock(returncode=0)) as run:
            PROBE.check_gateway("192.168.6.105")
        self.assertEqual(run.call_args.args[0],
                         ["ping", "-4", "-I", "192.168.6.105", "-c", "3", "-W", "3", "192.168.4.1"])

    def test_mdns_requires_the_expected_bridge(self):
        info = Mock()
        info.parsed_addresses.return_value = ["192.168.4.35"]
        self.assertTrue(PROBE.matches_bridge(info, "192.168.4.35", "ipv4"))
        self.assertFalse(PROBE.matches_bridge(info, "192.168.4.36", "ipv4"))
        self.assertFalse(PROBE.matches_bridge(None, "192.168.4.35", "ipv4"))

    def test_all_three_jobs_have_distinct_addresses_and_no_credentials(self):
        rendered = subprocess.check_output(["kustomize", "build", str(APP / "app")])
        resources = json.loads(subprocess.check_output(["yq", "ea", "-o=json", "[.]"], input=rendered))
        jobs = [resource for resource in resources if resource["kind"] == "Job"]
        self.assertEqual(len(jobs), 3)
        nodes, addresses = set(), set()
        for job in jobs:
            spec = job["spec"]
            pod = spec["template"]["spec"]
            nodes.add(pod["nodeSelector"]["kubernetes.io/hostname"])
            annotation = spec["template"]["metadata"]["annotations"]["k8s.v1.cni.cncf.io/networks"]
            network = json.loads(annotation)[0]
            self.assertEqual((network["name"], network["namespace"], network["interface"]),
                             ("iot", "kube-system", "net1"))
            addresses.add(network["ips"][0])
            container = pod["containers"][0]
            environment = {env["name"]: env for env in container["env"]}
            self.assertEqual(environment["IOT_ADDRESS"]["value"] + "/22", network["ips"][0])
            self.assertEqual(environment["LUTRON_ADDRESS"]["value"], "192.168.4.35")
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertEqual(pod["restartPolicy"], "Never")
            self.assertEqual(spec["backoffLimit"], 0)
            self.assertNotIn("ttlSecondsAfterFinished", spec)
            self.assertLessEqual(spec["activeDeadlineSeconds"], 300)
            self.assertEqual(container["securityContext"]["capabilities"], {"drop": ["ALL"]})
            self.assertEqual(pod["securityContext"]["sysctls"],
                             [{"name": "net.ipv4.ping_group_range", "value": "568 568"}])
            self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
            self.assertNotIn("envFrom", container)
            for volume in pod["volumes"]:
                self.assertEqual(set(volume), {"name", "configMap"})
        self.assertEqual(nodes, {"hcc5", "hcc6", "hcc7"})
        self.assertEqual(addresses, {"192.168.6.105/22", "192.168.6.106/22", "192.168.6.107/22"})


if __name__ == "__main__":
    unittest.main()
