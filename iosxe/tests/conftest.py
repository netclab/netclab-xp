"""Renders every example once and runs a composed Request's checks on recorded answers.

The checks are the compositions' own `logic:`, taken from `crossplane composition render`,
and they see what provider-http gives them: the Request's `forProvider` with `response`
beside it, and Secret values in place of `{{ name:namespace:key }}`.

By default the functions run once for the whole session and the render engine is a local
Crossplane binary; `--render=docker` renders each time in Docker, as the CLI does alone.
"""

import base64
import copy
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import time
import urllib.request
from collections import namedtuple
from itertools import count
from pathlib import Path

import jq
import pytest
import yaml

TESTS = Path(__file__).resolve().parent
IOSXE = TESTS.parent
VERSION = "17.18.02"
FIXTURES = TESTS / "fixtures" / VERSION
NAMESPACE = "lab"

# The floors of iosxe/apis/crossplane.yaml.
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
# It is not the floor of iosxe/apis/crossplane.yaml: a cluster checks that, not a render.
ENGINE = "v2.4.3"
ENGINES = "https://releases.crossplane.io/stable"

SECRET_REF = re.compile(r"\{\{\s*([^:\s{}]+):([^:\s{}]+):([^:\s{}]+)\s*\}\}")


EXAMPLES = sorted((IOSXE / "examples").glob("*/*.yaml"))

# The uid of every Secret below; record.sh writes the marks it gives.
SECRET_UID = "00000000-0000-4000-8000-000000000001"


def secrets(values=None):
    """The examples' Secrets, holding what secrets.json holds unless given `values`."""
    if values is None:
        values = json.loads((FIXTURES / "secrets.json").read_text())
    return [
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": name, "namespace": NAMESPACE, "uid": SECRET_UID},
            "data": {k: base64.b64encode(v.encode()).decode() for k, v in data.items()},
        }
        for name, data in values.items()
    ]


def in_namespace(path):
    """An example as applied: examples name no namespace, the lab's XRs live in one."""
    doc = yaml.safe_load(path.read_text())
    doc["metadata"]["namespace"] = NAMESPACE
    return doc


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


@pytest.fixture(scope="session")
def functions(request, tmp_path_factory):
    """The Functions file the renders use: with --render=local, each Function's container
    started once, the file pointing at it, and the containers removed at the end."""
    path = tmp_path_factory.mktemp("functions") / "functions.yaml"
    docs = list(yaml.safe_load_all(FUNCTIONS))
    if request.config.getoption("render") == "docker":
        path.write_text(FUNCTIONS)
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
        path.write_text(yaml.safe_dump_all(docs))
        yield path, [f"--crossplane-binary={engine()}"]
    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "-f", *started], check=False, capture_output=True
            )


@pytest.fixture(scope="session")
def render(tmp_path_factory, functions):
    """Renders an XR with the composition of its directory under apis/, `required` as the
    resources it requires (unless given, the other examples, all Ready, and the Secrets),
    and `observed` as the resources it composed before, with the Usage of its Device
    Ready unless given, as a cluster has it at once: the XR as rendered, and its composed
    resources by composition-resource-name."""
    tmp = tmp_path_factory.mktemp("render")
    functions, engine_args = functions
    examples = [observed(in_namespace(p), True) for p in EXAMPLES]
    renders = count()
    name = "crossplane.io/composition-resource-name"

    def _render(directory, xr, observed=(), required=None):
        n = next(renders)
        path = tmp / f"xr-{n}.yaml"
        path.write_text(yaml.safe_dump(xr))
        observed = list(observed)
        device = xr.get("spec", {}).get("deviceRef", {}).get("name")
        usage = f"after-device-{device}"
        if device and not any(
            o["metadata"].get("annotations", {}).get(name) == usage for o in observed
        ):
            observed.append(device_usage(usage))
        observed_path = tmp / f"observed-{n}.yaml"
        observed_path.write_text(yaml.safe_dump_all(observed))
        if required is None:
            # The XR among them would stand in for the XR rendered.
            same = (xr["kind"], xr["metadata"]["name"])
            required = [
                e for e in examples if (e["kind"], e["metadata"]["name"]) != same
            ] + secrets()
        required_path = tmp / f"required-{n}.yaml"
        required_path.write_text(yaml.safe_dump_all(required))
        result = subprocess.run(
            [
                "crossplane",
                "composition",
                "render",
                str(path),
                str(IOSXE / "apis" / directory / "composition.yaml"),
                str(functions),
                f"--required-resources={required_path}",
                f"--observed-resources={observed_path}",
                *engine_args,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        return Rendered(
            docs[0], {d["metadata"]["annotations"][name]: d for d in docs[1:]}
        )

    return _render


def observed(resource, ready):
    """A resource composed before, as Crossplane observes it, Ready or not."""
    out = copy.deepcopy(resource)
    out["status"] = {
        "conditions": [
            {
                "type": "Ready",
                "status": "True" if ready else "False",
                "reason": "Available" if ready else "Creating",
                "lastTransitionTime": "2024-01-01T00:00:00Z",
            }
        ]
    }
    return out


# The examples' Devices, Ready: every object waits on its Device before it composes.
DEVICES = [
    observed(in_namespace(p), True) for p in EXAMPLES if p.parent.name == "device"
]


def device_usage(resource_name):
    """The Usage of an XR's Device as composed before, Ready."""
    return observed(
        {
            "apiVersion": "protection.crossplane.io/v1beta1",
            "kind": "Usage",
            "metadata": {
                "name": resource_name,
                "namespace": NAMESPACE,
                "annotations": {
                    "crossplane.io/composition-resource-name": resource_name
                },
            },
        },
        True,
    )


def requests(resources):
    """The names of the composed Requests, sorted: no Usage."""
    return sorted(name for name, r in resources.items() if r["kind"] == "Request")


@pytest.fixture(scope="session")
def rendered(render):
    """Each example's composed resources by XR name, then by composition-resource-name:
    all of them, rendered again with what the last render composed Ready until that
    composes nothing more."""
    out = {}
    for example in EXAMPLES:
        if example.parent.name == "device":
            continue
        xr = in_namespace(example)
        resources = {}
        while True:
            before = [observed(r, True) for r in resources.values()]
            again = render(example.parent.name, xr, before).resources
            if again.keys() == resources.keys():
                break
            resources = again
        out[xr["metadata"]["name"]] = resources
    return out


def recorded(kind, state):
    """The router's answer recorded by record.sh for one kind in one state."""
    return json.loads((FIXTURES / kind / f"{state}.json").read_text())


def answered(kind, request, state, method="GET", status=None):
    """The Request as provider-http leaves it after `method`: the router's answer the one
    recorded for `kind` in `state`; after a write answered with `status`, the body is still
    that GET's, which provider-http keeps until the next GET."""
    out = observed(request, True)
    response = recorded(kind, state)
    body = response["body"]
    out["status"]["requestDetails"] = {"method": method}
    out["status"]["response"] = {
        "statusCode": response["statusCode"] if status is None else status,
        "body": body if isinstance(body, str) else json.dumps(body),
    }
    return out


def ready(rendered):
    """The rendered XR's Ready condition."""
    conditions = rendered.composite["status"]["conditions"]
    return {c["type"]: c["status"] for c in conditions}["Ready"]


def status(rendered):
    """The rendered XR's status, without its conditions."""
    return {k: v for k, v in rendered.composite["status"].items() if k != "conditions"}


def _secrets(text):
    values = json.loads((FIXTURES / "secrets.json").read_text())
    return SECRET_REF.sub(lambda m: values[m.group(1)][m.group(3)], text)


def check(request, field, response):
    """The result of a Request's `field` check (e.g. isRemovedCheck) on `response`."""
    for_provider = request["spec"]["forProvider"]
    context = copy.deepcopy(for_provider)
    payload = context.get("payload", {})
    if isinstance(payload.get("body"), str):
        payload["body"] = json.loads(payload["body"])
    context["response"] = {"headers": None, **response}
    program = jq.compile(_secrets(for_provider[field]["logic"]))
    result = program.input_value(context).first()
    assert isinstance(result, bool), f"{field} returned {result!r}"
    return result
