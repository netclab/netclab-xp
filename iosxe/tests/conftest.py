"""Renders every example once and runs a composed Request's checks on recorded answers.

The checks are the compositions' own `logic:`, taken from `crossplane composition render`,
and they see what provider-http gives them: the Request's `forProvider` with `response`
beside it, and Secret values in place of `{{ name:namespace:key }}`.
"""

import copy
import json
import re
import subprocess
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

SECRET_REF = re.compile(r"\{\{\s*([^:\s{}]+):([^:\s{}]+):([^:\s{}]+)\s*\}\}")


EXAMPLES = sorted((IOSXE / "examples").glob("*/*.yaml"))


def in_namespace(path):
    """An example as applied: examples name no namespace, the lab's XRs live in one."""
    doc = yaml.safe_load(path.read_text())
    doc["metadata"]["namespace"] = NAMESPACE
    return doc


Rendered = namedtuple("Rendered", "composite resources")


@pytest.fixture(scope="session")
def render(tmp_path_factory):
    """Renders an XR with the composition of its directory under apis/, `required` as the
    resources it requires (unless given, the other examples, all Ready), and `observed` as
    the resources it composed before: the XR as rendered, and its composed resources by
    composition-resource-name."""
    tmp = tmp_path_factory.mktemp("render")
    functions = tmp / "functions.yaml"
    functions.write_text(FUNCTIONS)
    examples = [observed(in_namespace(p), True) for p in EXAMPLES]
    renders = count()

    def _render(directory, xr, observed=(), required=None):
        n = next(renders)
        path = tmp / f"xr-{n}.yaml"
        path.write_text(yaml.safe_dump(xr))
        observed_path = tmp / f"observed-{n}.yaml"
        observed_path.write_text(yaml.safe_dump_all(observed))
        if required is None:
            # The XR among them would stand in for the XR rendered.
            same = (xr["kind"], xr["metadata"]["name"])
            required = [
                e for e in examples if (e["kind"], e["metadata"]["name"]) != same
            ]
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
