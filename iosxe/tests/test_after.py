"""after: each kind composes no Request and is not Ready until its Device and the objects
it names are Ready, keeps its Requests once it composed them, and holds back the delete of
each of those with a Usage."""

import functools

import pytest
from conftest import DEVICES, EXAMPLES, IOSXE, in_namespace, observed, requests, secrets

KINDS = sorted({p.parent.name for p in EXAMPLES} - {"device"})

# Two objects the XR waits on, neither of them the XR itself.
AFTER = [
    {"kind": "Ikev2Keyring", "name": "first"},
    {"kind": "IpsecTransformSet", "name": "second"},
]
# Its Device comes first, whatever the spec names.
WAITED = [{"kind": "Device", "name": "r1"}, *AFTER]
USAGES = [
    "after-device-r1",
    "after-ikev2keyring-first",
    "after-ipsectransformset-second",
]
DEVICES_NOT_READY = [observed(d, False) for d in DEVICES]


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
        if name == "no-device":
            return render(kind, xr(kind), required=secrets() + waited_on(True, True))
        if name == "device-not-ready":
            required = DEVICES_NOT_READY + secrets() + waited_on(True, True)
            return render(kind, xr(kind), required=required)
        if name == "absent":
            return render(kind, xr(kind), required=DEVICES)
        if name == "one-not-ready":
            return render(
                kind, xr(kind), required=DEVICES + secrets() + waited_on(True, False)
            )
        if name == "ready":
            return render(
                kind, xr(kind), required=DEVICES + secrets() + waited_on(True, True)
            )
        if name == "composed-then-one-not-ready":
            before = [
                observed(r, True) for r in _stage(kind, "ready").resources.values()
            ]
            required = DEVICES + secrets() + waited_on(True, False)
            return render(kind, xr(kind), before, required)
        raise ValueError(name)

    return _stage


@pytest.mark.parametrize("kind", KINDS)
def test_composes_no_request_without_its_device(stage, kind):
    # The objects that are there are held back all the same.
    rendered = stage(kind, "no-device")
    assert sorted(rendered.resources) == USAGES[1:]
    assert ready(rendered) == "False"


@pytest.mark.parametrize("kind", KINDS)
def test_composes_only_its_device_s_usage_while_the_objects_do_not_exist(stage, kind):
    rendered = stage(kind, "absent")
    assert sorted(rendered.resources) == ["after-device-r1"]
    assert ready(rendered) == "False"


@pytest.mark.parametrize("kind", KINDS)
def test_composes_no_request_while_its_device_is_not_ready(stage, kind):
    rendered = stage(kind, "device-not-ready")
    assert sorted(rendered.resources) == USAGES
    assert ready(rendered) == "False"


@pytest.mark.parametrize("kind", KINDS)
def test_composes_no_request_while_one_object_is_not_ready(stage, kind):
    rendered = stage(kind, "one-not-ready")
    assert sorted(rendered.resources) == USAGES
    assert ready(rendered) == "False"


@pytest.mark.parametrize("kind", KINDS)
def test_composes_its_requests_once_every_object_is_ready(stage, kind):
    assert requests(stage(kind, "ready").resources) != []


@pytest.mark.parametrize("kind", KINDS)
def test_keeps_its_requests_when_an_object_is_no_longer_ready(stage, kind):
    # A kind may compose more once its first Requests are Ready, never fewer.
    rendered = stage(kind, "composed-then-one-not-ready")
    assert set(requests(stage(kind, "ready").resources)) <= set(
        requests(rendered.resources)
    )


@pytest.mark.parametrize("kind", KINDS)
def test_holds_back_the_delete_of_its_device_and_each_object(stage, kind):
    rendered = stage(kind, "one-not-ready")
    xr = example(kind)
    for name, a in zip(USAGES, WAITED, strict=True):
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
def test_without_after_holds_back_only_its_device(rendered, xr):
    assert [r for r in rendered[xr] if r.startswith("after-")] == ["after-device-r1"]
