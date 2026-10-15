"""Renders every example once and runs a composed Request's checks on recorded answers.

The checks are the compositions' own `logic:`, taken from `crossplane composition render`,
and they see what provider-http gives them: the Request's `forProvider` with `response`
beside it, and Secret values in place of `{{ name:namespace:key }}`.
"""

import copy
import json
import re
import subprocess
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

SECRET_REF = re.compile(r"\{\{\s*([^:\s{}]+):([^:\s{}]+):([^:\s{}]+)\s*\}\}")


def _in_namespace(path):
    """An example as applied: examples name no namespace, the lab's XRs live in one."""
    doc = yaml.safe_load(path.read_text())
    doc["metadata"]["namespace"] = NAMESPACE
    return doc


@pytest.fixture(scope="session")
def rendered(tmp_path_factory):
    """Each example's composed resources by XR name, then by composition-resource-name."""
    tmp = tmp_path_factory.mktemp("render")
    functions = tmp / "functions.yaml"
    functions.write_text(FUNCTIONS)
    examples = sorted((IOSXE / "examples").glob("*/*.yaml"))
    devices = tmp / "devices.yaml"
    devices.write_text(
        yaml.safe_dump_all(
            _in_namespace(p) for p in examples if p.parent.name == "device"
        )
    )

    out = {}
    for example in examples:
        if example.parent.name == "device":
            continue
        xr = tmp / f"{example.parent.name}-{example.name}"
        xr.write_text(yaml.safe_dump(_in_namespace(example)))
        result = subprocess.run(
            [
                "crossplane",
                "composition",
                "render",
                str(xr),
                str(IOSXE / "apis" / example.parent.name / "composition.yaml"),
                str(functions),
                f"--required-resources={devices}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        name = docs[0]["metadata"]["name"]
        out[name] = {
            d["metadata"]["annotations"]["crossplane.io/composition-resource-name"]: d
            for d in docs[1:]
        }
    return out


def recorded(kind, state):
    """The router's answer recorded by record.sh for one kind in one state."""
    return json.loads((FIXTURES / kind / f"{state}.json").read_text())


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
