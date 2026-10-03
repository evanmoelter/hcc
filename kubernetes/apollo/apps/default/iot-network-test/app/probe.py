import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import threading


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def parse_ip_output(args, output):
    if args[0] == "address":
        return [{"addr_info": [{"local": address, "prefixlen": int(prefix)}
                               for address, prefix in re.findall(r"\binet\s+([0-9.]+)/(\d+)", output)]}]
    routes = []
    for line in output.splitlines():
        fields = line.split()
        if "dev" not in fields:
            continue
        route = {"dev": fields[fields.index("dev") + 1]}
        if "src" in fields:
            route["src"] = fields[fields.index("src") + 1]
        routes.append(route)
    return routes


def ip_state(*args):
    output = subprocess.check_output(["ip", "-4", *args], text=True, stderr=subprocess.PIPE)
    return parse_ip_output(args, output)


def check_address(addresses, expected):
    require(any(a.get("local") == expected and a.get("prefixlen") == 22
                for interface in addresses for a in interface.get("addr_info", [])),
            "net1 must have the expected IPv4 address and /22 prefix")


def check_route(routes, device, source=None):
    require(bool(routes) and all(route.get("dev") == device for route in routes),
            f"route must use {device}")
    if source:
        require(all(route.get("prefsrc", route.get("src")) == source for route in routes),
                "route must use the expected source address")


def check_gateway(address):
    result = subprocess.run(["ping", "-4", "-I", address, "-c", "3", "-W", "3", "192.168.4.1"],
                            capture_output=True, timeout=15)
    require(result.returncode == 0, "IoT gateway did not answer ICMP through net1")


def check_lutron_tcp(address, bridge):
    check_route(ip_state("route", "get", bridge), "net1", address)
    with socket.create_connection((bridge, 8081), timeout=5, source_address=(address, 0)) as connection:
        require(connection.getsockname()[0] == address, "Lutron connection used the wrong source")


def check_cluster():
    targets = socket.getaddrinfo("kubernetes.default.svc.cluster.local", 443,
                                 family=socket.AF_INET, type=socket.SOCK_STREAM)
    require(bool(targets), "cluster DNS did not return an IPv4 address")
    target = targets[0][4]
    check_route(ip_state("route", "get", target[0]), "eth0")
    with socket.create_connection(target, timeout=5):
        pass


def check_outbound():
    target = socket.getaddrinfo("www.home-assistant.io", 443, family=socket.AF_INET,
                               type=socket.SOCK_STREAM)[0][4]
    check_route(ip_state("route", "get", target[0]), "eth0")
    with socket.create_connection(target, timeout=5) as connection:
        with ssl.create_default_context().wrap_socket(connection, server_hostname="www.home-assistant.io"):
            pass


def matches_bridge(info, bridge, ip_version):
    return info is not None and bridge in info.parsed_addresses(ip_version)


def check_mdns(address, bridge):
    from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf

    found = threading.Event()

    def receive(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Removed:
            return
        info = zeroconf.get_service_info(service_type, name, timeout=2000)
        if matches_bridge(info, bridge, IPVersion.V4Only):
            found.set()

    with Zeroconf(interfaces=[address], ip_version=IPVersion.V4Only) as zeroconf:
        browser = ServiceBrowser(zeroconf, ["_lutron._tcp.local.", "_hap._tcp.local."], handlers=[receive])
        try:
            require(found.wait(45), "no Lutron mDNS service resolved to the expected bridge on net1")
        finally:
            browser.cancel()


def main():
    address = str(ipaddress.IPv4Address(os.environ["IOT_ADDRESS"]))
    bridge = str(ipaddress.IPv4Address(os.environ["LUTRON_ADDRESS"]))
    checks = {
        "iot_address": lambda: check_address(ip_state("address", "show", "dev", "net1"), address),
        "primary_default_route": lambda: check_route(ip_state("route", "show", "default"), "eth0"),
        "iot_gateway_route": lambda: check_route(ip_state("route", "get", "192.168.4.1"), "net1", address),
        "iot_gateway_ping": lambda: check_gateway(address),
        "lutron_tcp": lambda: check_lutron_tcp(address, bridge),
        "cluster_dns_and_api_tcp": check_cluster,
        "outbound_dns_and_tls": check_outbound,
        "lutron_mdns": lambda: check_mdns(address, bridge),
    }
    failed = []
    for name, check in checks.items():
        try:
            check()
        except Exception as error:
            failed.append(name)
            print(json.dumps({"node": os.environ["NODE_NAME"], "check": name,
                              "result": "FAIL", "error": str(error)}), flush=True)
        else:
            print(json.dumps({"node": os.environ["NODE_NAME"], "check": name, "result": "PASS"}), flush=True)
    print(json.dumps({"node": os.environ["NODE_NAME"], "result": "FAIL" if failed else "PASS",
                      "failed_checks": failed}), flush=True)
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
