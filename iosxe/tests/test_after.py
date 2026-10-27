"""after: each kind composes no Request and is not Ready until the objects it names are
Ready, keeps its Requests once it composed them, and holds back the delete of each of those
objects with a Usage."""

import functools

import pytest
from conftest import EXAMPLES, IOSXE, in_namespace, observed

KINDS = sorted({p.parent.name for p in EXAMPLES} - {"device"})
DEVICES = [in_namespace(p) for p in EXAMPLES if p.parent.name == "device"]

# Two objects the XR waits on, neither of them the XR itself.
AFTER = [
    {"kind": "Ikev2Keyring", "name": "first"},
    {"kind": "IpsecTransformSet", "name": "second"},
]
USAGES = ["after-ikev2keyring-first", "after-ipsectransformset-second"]


def example(directory):
    return in_namespace(IOSXE / "examples" / directory / "r1.yaml")


def waited_on(first, second):
    """The objects of AFTER, Ready or not."""
    out = []
    for directory, a, ready in [
        ("ikev2keyring", AFTER[0], first),
        ("ipsectransformset", AFTER[1], second),
    ]:
        doc = example(directory)
        doc["metadata"]["name"] = a["name"]
        out.append(observed(doc, ready))
    return out


def ready(rendered):
    conditions = rendered.composite["status"]["conditions"]
    return {c["type"]: c["status"] for c in conditions}["Ready"]


def requests(rendered):
    return sorted(r for r in rendered.resources if not r.startswith("after-"))


@pytest.fixture(scope="module")
def stage(render):
    """stage(kind, name): the kind's example with AFTER, rendered in one of the states
    below, each once."""

    def xr(kind):
        doc = example(kind)
        doc["spec"]["after"] = AFTER
        return doc

    @functools.cache
    def _stage(kind, name):
        if name == "absent":
            return render(kind, xr(kind), required=DEVICES)
        if name == "one-not-ready":
            return render(kind, xr(kind), required=DEVICES + waited_on(True, False))
        if name == "ready":
            return render(kind, xr(kind), required=DEVICES + waited_on(True, True))
        if name == "composed-then-one-not-ready":
            before = [
                observed(r, True) for r in _stage(kind, "ready").resources.values()
            ]
            required = DEVICES + waited_on(True, False)
            return render(kind, xr(kind), before, required)
        raise ValueError(name)

    return _stage


@pytest.mark.parametrize("kind", KINDS)
def test_composes_nothing_while_the_objects_do_not_exist(stage, kind):
    rendered = stage(kind, "absent")
    assert rendered.resources == {}
    assert ready(rendered) == "False"


@pytest.mark.parametrize("kind", KINDS)
def test_composes_no_request_while_one_object_is_not_ready(stage, kind):
    rendered = stage(kind, "one-not-ready")
    assert sorted(rendered.resources) == USAGES
    assert ready(rendered) == "False"


@pytest.mark.parametrize("kind", KINDS)
def test_composes_its_requests_once_every_object_is_ready(stage, kind):
    assert requests(stage(kind, "ready")) != []


@pytest.mark.parametrize("kind", KINDS)
def test_keeps_its_requests_when_an_object_is_no_longer_ready(stage, kind):
    # A kind may compose more once its first Requests are Ready, never fewer.
    rendered = stage(kind, "composed-then-one-not-ready")
    assert set(requests(stage(kind, "ready"))) <= set(requests(rendered))


@pytest.mark.parametrize("kind", KINDS)
def test_holds_back_the_delete_of_each_object(stage, kind):
    rendered = stage(kind, "one-not-ready")
    xr = example(kind)
    for name, a in zip(USAGES, AFTER, strict=True):
        assert rendered.resources[name]["spec"] == {
            "of": {
                "apiVersion": "iosxe.netclab.dev/v1alpha1",
                "kind": a["kind"],
                "resourceRef": {"name": a["name"]},
            },
            "by": {
                "apiVersion": xr["apiVersion"],
                "kind": xr["kind"],
                "resourceRef": {"name": xr["metadata"]["name"]},
            },
            "replayDeletion": True,
        }


@pytest.mark.parametrize(
    "xr",
    sorted(
        in_namespace(p)["metadata"]["name"]
        for p in EXAMPLES
        if p.parent.name != "device" and "after" not in in_namespace(p)["spec"]
    ),
)
def test_composes_no_usage_without_after(rendered, xr):
    assert [r for r in rendered[xr] if r.startswith("after-")] == []
