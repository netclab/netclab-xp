"""Renders the Connection with `crossplane composition render`.

By default the functions run once for the whole session and the render engine is a local
Crossplane binary; `--render=docker` renders each time in Docker, as the CLI does alone.
function-aws-vpn is served from this checkout, or with FUNCTION_IMAGE set from that image,
as Crossplane runs it: uid 2000.
"""

import base64
import copy
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
from collections import namedtuple
from itertools import count
from pathlib import Path

import pytest
import yaml

TESTS = Path(__file__).resolve().parent
AWS_VPN = TESTS.parent
NAMESPACE = "lab"
EXAMPLE = AWS_VPN / "examples" / "connection" / "edge1.yaml"
COMPOSITION = AWS_VPN / "apis" / "connection" / "composition.yaml"

# The floors of aws-vpn/apis/crossplane.yaml.
FUNCTIONS = """\
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: crossplane-contrib-function-go-templating
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-go-templating:v0.12.0
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: crossplane-contrib-function-auto-ready
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-auto-ready:v0.5.2
"""

# The render engine with --render=local, fixed so that a run does not follow a moving tag.
ENGINE = "v2.4.3"
ENGINES = "https://releases.crossplane.io/stable"

Rendered = namedtuple("Rendered", "composite resources")


def pytest_addoption(parser):
    parser.addoption(
        "--render",
        choices=["local", "docker"],
        default="local",
        help="local: the functions once per session and a local engine (the default); "
        "docker: every render in Docker",
    )


def engine():
    """The Crossplane binary of ENGINE for this machine, downloaded once and checked."""
    arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine()]
    url = f"{ENGINES}/{ENGINE}/bin/{platform.system().lower()}_{arch}/crossplane"
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = cache / "netclab-xp" / f"crossplane-{ENGINE}-{arch}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url) as r:
            binary = r.read()
        with urllib.request.urlopen(f"{url}.sha256") as r:
            want = r.read().decode().split()[0]
        if hashlib.sha256(binary).hexdigest() != want:
            raise RuntimeError(f"{url}: checksum differs from {url}.sha256")
        partial = path.with_suffix(".part")
        partial.write_bytes(binary)
        partial.chmod(0o755)
        partial.rename(path)
    return path


def listening(port, wait=60):
    """Whether a gRPC server answers on 127.0.0.1:port within `wait` seconds: its HTTP/2
    SETTINGS frame, which Docker's proxy alone, with nothing behind it, never sends."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
                s.sendall(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n")
                s.settimeout(1)
                if s.recv(9):
                    return True
        except OSError:
            pass
        time.sleep(0.2)
    return False


IMAGE = os.environ.get("FUNCTION_IMAGE")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def function_aws_vpn(tmp_path_factory):
    """function-aws-vpn listening on a free port, and its Function pointing there."""
    port = free_port()
    # every interface: a render engine in Docker calls it from a container
    args = ["--insecure", "--address", f"0.0.0.0:{port}"]
    if IMAGE is None:
        command = [sys.executable, "-m", "function.main", *args]
    else:
        name = f"function-aws-vpn-{port}"
        command = [
            "docker",
            "run",
            "--rm",
            "--init",
            "--name",
            name,
            "--network",
            "host",
        ]
        command += ["--user", "2000:2000", IMAGE, *args]
    log = tmp_path_factory.mktemp("function-aws-vpn") / "function.log"
    with log.open("w") as out:
        server = subprocess.Popen(
            command, cwd=AWS_VPN, stdout=out, stderr=subprocess.STDOUT
        )
    try:
        if not listening(port):
            raise RuntimeError(
                f"function-aws-vpn not listening on {port}: {log.read_text()}"
            )
        yield {
            "apiVersion": "pkg.crossplane.io/v1",
            "kind": "Function",
            "metadata": {
                "name": "netclab-function-aws-vpn",
                "annotations": {
                    "render.crossplane.io/runtime": "Development",
                    "render.crossplane.io/runtime-development-target": f"localhost:{port}",
                },
            },
            "spec": {"package": "xpkg.upbound.io/netclab/function-aws-vpn:v0.0.0"},
        }
    finally:
        if IMAGE is not None:
            subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, check=False
            )
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(scope="session")
def functions(request, tmp_path_factory, function_aws_vpn):
    """The Functions file the renders use: with --render=local, each Function's container
    started once, the file pointing at it, and the containers removed at the end."""
    path = tmp_path_factory.mktemp("functions") / "functions.yaml"
    docs = list(yaml.safe_load_all(FUNCTIONS))
    if request.config.getoption("render") == "docker":
        path.write_text(yaml.safe_dump_all([*docs, function_aws_vpn]))
        yield path, []
        return
    started = []
    try:
        for doc in docs:
            started.append(
                subprocess.run(
                    ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::9443"]
                    + [doc["spec"]["package"], "--insecure"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            )
            port = (
                subprocess.run(
                    ["docker", "port", started[-1], "9443/tcp"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.split(":")[-1]
                .strip()
            )
            if not listening(int(port)):
                raise RuntimeError(f"{doc['metadata']['name']} not listening on {port}")
            doc["metadata"]["annotations"] = {
                "render.crossplane.io/runtime": "Development",
                "render.crossplane.io/runtime-development-target": f"127.0.0.1:{port}",
            }
        path.write_text(yaml.safe_dump_all([*docs, function_aws_vpn]))
        yield path, [f"--crossplane-binary={engine()}"]
    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "-f", *started], check=False, capture_output=True
            )


@pytest.fixture(scope="session")
def render(tmp_path_factory, functions):
    """Renders a Connection with `required` as the resources it requires (unless given, the
    Device and the user's Secret) and `observed` as the resources it composed before: the
    XR as rendered, and its composed resources by composition-resource-name."""
    tmp = tmp_path_factory.mktemp("render")
    functions, engine_args = functions
    renders = count()

    def _render(xr, observed=(), required=None):
        n = next(renders)
        files = {}
        for name, docs in (
            ("xr", [xr]),
            ("observed", list(observed)),
            ("required", [device(), secret()] if required is None else list(required)),
        ):
            files[name] = tmp / f"{name}-{n}.yaml"
            files[name].write_text(yaml.safe_dump_all(docs))
        result = subprocess.run(
            [
                "crossplane",
                "composition",
                "render",
                str(files["xr"]),
                str(COMPOSITION),
                str(functions),
                f"--required-resources={files['required']}",
                f"--observed-resources={files['observed']}",
                *engine_args,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        name = "crossplane.io/composition-resource-name"
        return Rendered(
            docs[0], {d["metadata"]["annotations"][name]: d for d in docs[1:]}
        )

    return _render


def example(status=None, **customer_gateway):
    """The package's example as applied, its customer gateway updated, with a status."""
    xr = yaml.safe_load(EXAMPLE.read_text())
    xr["metadata"]["uid"] = "00000000-0000-4000-8000-0000000000aa"
    xr["spec"]["customerGateway"].update(customer_gateway)
    if status:
        xr["status"] = status
    return xr


def observed(resource, ready=True):
    """A resource composed before, as Crossplane observes it, Ready or not; its status kept."""
    out = copy.deepcopy(resource)
    out.setdefault("status", {})["conditions"] = [
        {
            "type": "Ready",
            "status": "True" if ready else "False",
            "reason": "Available" if ready else "Creating",
            "lastTransitionTime": "2024-01-01T00:00:00Z",
        }
    ]
    return out


def composed(name, kind, api_version, status=None, data=None):
    """A resource the Connection composed before, by its composition-resource-name."""
    out = {
        "apiVersion": api_version,
        "kind": kind,
        "metadata": {
            "name": f"x-{name}",
            "namespace": NAMESPACE,
            "annotations": {"crossplane.io/composition-resource-name": name},
        },
    }
    if status is not None:
        out["status"] = status
    if data is not None:
        out["data"] = data
    return observed(out)


def device():
    """Device edge1, Ready."""
    return observed(
        {
            "apiVersion": "iosxe.netclab.dev/v1alpha1",
            "kind": "Device",
            "metadata": {"name": "edge1", "namespace": NAMESPACE},
            "spec": {
                "address": "172.18.0.104",
                "insecureSkipTLSVerify": True,
                "credentialsSecretRef": {"name": "edge1-creds", "key": "basic"},
            },
        }
    )


def b64(value):
    return base64.b64encode(value.encode()).decode()


def secret(tunnel1="Key1", tunnel2="Key2"):
    """The user's Secret of the example, holding these keys; None leaves a key out."""
    data = {k: b64(v) for k, v in (("tunnel1", tunnel1), ("tunnel2", tunnel2)) if v}
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "edge1-aws-keys", "namespace": NAMESPACE},
        "data": data,
    }


# The VPN connection's addresses, as the provider reports them once AWS has it available.
AT_PROVIDER = {
    "id": "vpn-0123456789abcdef0",
    "customerGatewayId": "cgw-0123456789abcdef0",
    "tunnel1Address": "203.0.113.1",
    "tunnel2Address": "203.0.113.2",
    "tunnel1CgwInsideAddress": "169.254.10.2",
    "tunnel2CgwInsideAddress": "169.254.10.6",
    "tunnel1VgwInsideAddress": "169.254.10.1",
    "tunnel2VgwInsideAddress": "169.254.10.5",
    "tunnel1InsideCidr": "169.254.10.0/30",
    "tunnel2InsideCidr": "169.254.10.4/30",
    "tunnel1BgpAsn": "64512",
    "tunnel2BgpAsn": "64512",
}


def vpn_connection(at_provider=None):
    """The VPNConnection composed before, with this atProvider (AT_PROVIDER unless given)."""
    return composed(
        "vpn-connection",
        "VPNConnection",
        "ec2.aws.m.upbound.io/v1beta1",
        {"atProvider": AT_PROVIDER if at_provider is None else at_provider},
    )


def applied(tunnel1="Key1", tunnel2="Key2"):
    """The Connection's Secret of applied keys, composed before."""
    return composed(
        "keys", "Secret", "v1", data={"tunnel1": b64(tunnel1), "tunnel2": b64(tunnel2)}
    )


def tunnel(n, up=True):
    """Tunnel n's TunnelInterface composed before, up on its key or down."""
    oper = (
        {"interface": "ready", "activePeers": "1/1"}
        if up
        else {
            "interface": "lower-layer-down",
            "activePeers": "0/1",
        }
    )
    return composed(
        f"tunnel-{n}", "TunnelInterface", "iosxe.netclab.dev/v1alpha1", {"oper": oper}
    )


def values(rendered):
    """The applied keys the Connection composes, decoded."""
    data = rendered.resources["keys"]["data"]
    return {k: base64.b64decode(v).decode() for k, v in data.items()}


def status(rendered):
    """The rendered XR's status, without its conditions."""
    return {k: v for k, v in rendered.composite["status"].items() if k != "conditions"}


def bgp(code, neighbours=()):
    response = {"statusCode": code}
    if code == 200:
        response["body"] = json.dumps(
            {"Cisco-IOS-XE-bgp-oper:neighbors": {"neighbor": list(neighbours)}}
        )
    return composed(
        "bgp", "Request", "http.m.crossplane.io/v1alpha2", {"response": response}
    )


def neighbour(afi, vrf, address, state):
    return {
        "afi-safi": afi,
        "vrf-name": vrf,
        "neighbor-id": address,
        "session-state": state,
    }
