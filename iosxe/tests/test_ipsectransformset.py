"""IpsecTransformSet: its name, its modes, the check its Request observes with on the
router's recorded answers, and the status it makes of them."""

import json
from functools import partial

import pytest
from conftest import (
    DEVICES,
    IOSXE,
    check,
    in_namespace,
    ready,
    recorded,
    requests,
    status,
)
from conftest import answered as _answered

KIND = "ipsectransformset"
XR = "r1--classical-ts--771f3cb2"
answered = partial(_answered, KIND)


def example(policy=None, drop=(), **spec):
    """The example in `policy`, without the fields in `drop`, with `spec` over it."""
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    if policy:
        xr["spec"]["managementPolicy"] = policy
    else:
        del xr["spec"]["managementPolicy"]
    for field in drop:
        del xr["spec"][field]
    xr["spec"].update(spec)
    return xr


def thin(name="CLASSICAL-TS", xr_name=XR):
    """An object as Step 3 imports it: deviceRef and name, no mode."""
    return {
        "apiVersion": "iosxe.netclab.dev/v1alpha1",
        "kind": "IpsecTransformSet",
        "metadata": {"name": xr_name, "namespace": "lab"},
        "spec": {"deviceRef": {"name": "r1"}, "name": name},
    }


def request(render, xr):
    return render(KIND, xr, required=DEVICES).resources["transform-set"]


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("CLASSICAL-TS", "r1--classical-ts--771f3cb2"),
        ("__A..b__", "r1--a-b--"),
    ],
)
def test_an_object_under_another_name_composes_nothing(render, name, want):
    xr = thin(name, "my-transform-set")
    rendered = render(KIND, xr, required=DEVICES)
    assert rendered.resources == {}
    wants = rendered.composite["status"]["wantsName"]
    assert wants.startswith(want) and len(wants) <= 63
    assert ready(rendered) == "False"
    xr["metadata"]["name"] = wants
    assert requests(render(KIND, xr, required=DEVICES).resources) == ["transform-set"]


@pytest.mark.parametrize(
    ("policy", "policies", "writes"),
    [
        (None, ["Observe"], []),
        (
            "Manage",
            ["Observe", "Create", "Update"],
            [("CREATE", "PATCH"), ("UPDATE", "PATCH")],
        ),
        (
            "FullControl",
            ["*"],
            [("CREATE", "PUT"), ("UPDATE", "PUT"), ("REMOVE", "DELETE")],
        ),
    ],
)
def test_the_mode_decides_what_the_request_may_do(render, policy, policies, writes):
    spec = request(render, example(policy))["spec"]
    assert spec["managementPolicies"] == policies
    assert [
        (m["action"], m["method"])
        for m in spec["forProvider"]["mappings"]
        if m["action"] != "OBSERVE"
    ] == writes


@pytest.mark.parametrize(
    ("spec", "recording"),
    [
        ({}, "transform-set-patch"),
        # 128 is named, or the merge would leave another length in place.
        ({"keyBits": 128}, "transform-set-patch-key-bit-128"),
    ],
)
def test_manage_sends_the_patch_the_router_merged(render, spec, recording):
    for_provider = request(render, example("Manage", **spec))["spec"]["forProvider"]
    sent = recorded(KIND, recording)["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


@pytest.mark.parametrize(
    ("spec", "state"),
    [
        ({}, "transform-set-applied"),
        # The router leaves out its default length, so the PUT does too.
        ({"keyBits": 128}, "transform-set-key-bit-128"),
    ],
)
def test_full_control_puts_what_the_router_then_returns(render, spec, state):
    body = request(render, example("FullControl", **spec))["spec"]["forProvider"]
    assert json.loads(body["payload"]["body"]) == recorded(KIND, state)["body"]


@pytest.mark.parametrize(
    ("drop", "spec", "state", "manage", "full_control"),
    [
        ((), {}, "transform-set-applied", True, True),
        ((), {}, "transform-set-patched", True, True),
        ((), {"keyBits": 128}, "transform-set-patched-key-bit-128", True, True),
        # A value of the spec the router lacks.
        ((), {}, "transform-set-key-bit-128", False, False),
        ((), {}, "transform-set-transport", False, False),
        ((), {}, "transform-set-aes-with-hmac", False, False),
        ((), {}, "transform-set-absent", False, False),
        # The spec leaves the length out: Manage leaves it, FullControl puts back
        # the router's default.
        (("keyBits",), {}, "transform-set-applied", True, False),
        (("keyBits",), {}, "transform-set-key-bit-128", True, True),
    ],
)
def test_check_is_the_mode_write_changing_nothing(
    render, drop, spec, state, manage, full_control
):
    for policy, expected in [("Manage", manage), ("FullControl", full_control)]:
        req = request(render, example(policy, drop, **spec))
        assert check(req, "expectedResponseCheck", recorded(KIND, state)) is expected


@pytest.fixture(scope="module")
def after_get(render):
    """The XR rendered with its Request answered by a GET of the router in `state`."""

    def _after_get(xr, state):
        return render(KIND, xr, [answered(request(render, xr), state)], DEVICES)

    return _after_get


@pytest.mark.parametrize(
    ("state", "observed"),
    [
        (
            "transform-set-applied",
            {"esp": "esp-gcm", "keyBits": 256, "mode": "tunnel"},
        ),
        # The router's default length, which its answer leaves out.
        (
            "transform-set-key-bit-128",
            {"esp": "esp-gcm", "keyBits": 128, "mode": "tunnel"},
        ),
        (
            "transform-set-aes-with-hmac",
            {
                "esp": "esp-aes",
                "keyBits": 256,
                "espHmac": "esp-sha256-hmac",
                "mode": "tunnel",
            },
        ),
    ],
)
def test_a_thin_object_shows_the_router_in_the_shape_of_the_spec(
    after_get, state, observed
):
    rendered = after_get(thin(), state)
    assert status(rendered) == {"observed": observed, "drift": [], "extra": []}
    assert ready(rendered) == "True"


def test_a_section_gone_from_the_router_is_not_ready(after_get):
    xr = thin()
    xr["status"] = {"observed": {"esp": "esp-gcm"}, "drift": [], "extra": []}
    rendered = after_get(xr, "transform-set-absent")
    assert "observed" not in status(rendered)
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "drop", "state", "drift", "extra", "is_ready"),
    [
        (
            None,
            (),
            "transform-set-aes-with-hmac",
            [{"field": "esp", "device": ["esp-aes"], "spec": ["esp-gcm"]}],
            [],
            "False",
        ),
        (
            "Manage",
            (),
            "transform-set-key-bit-128",
            [{"field": "keyBits", "device": ["128"], "spec": ["256"]}],
            [],
            "False",
        ),
        # A field the spec leaves out: compared in FullControl alone.
        ("Manage", ("keyBits",), "transform-set-applied", [], [], "True"),
        (
            "FullControl",
            ("keyBits",),
            "transform-set-applied",
            [],
            [{"field": "keyBits", "device": ["256"]}],
            "False",
        ),
        # The router's default where the spec leaves the field out is no extra.
        ("FullControl", ("keyBits",), "transform-set-key-bit-128", [], [], "True"),
        (
            "FullControl",
            ("keyBits",),
            "transform-set-aes-with-hmac",
            [{"field": "esp", "device": ["esp-aes"], "spec": ["esp-gcm"]}],
            [
                {"field": "keyBits", "device": ["256"]},
                {"field": "espHmac", "device": ["esp-sha256-hmac"]},
            ],
            "False",
        ),
    ],
)
def test_drift_and_extra_follow_the_mode(
    after_get, policy, drop, state, drift, extra, is_ready
):
    rendered = after_get(example(policy, drop), state)
    assert status(rendered)["drift"] == drift
    assert status(rendered)["extra"] == extra
    assert ready(rendered) == is_ready


def test_a_write_that_succeeded_records_what_it_put_back(render):
    xr = example("Manage")
    req = request(render, xr)
    before = render(KIND, xr, [answered(req, "transform-set-transport")], DEVICES)
    xr["status"] = status(before)
    code = recorded(KIND, "transform-set-patch")["statusCode"]
    rendered = render(
        KIND, xr, [answered(req, "transform-set-transport", "PATCH", code)], DEVICES
    )
    assert status(rendered)["drift"] == []
    assert status(rendered)["reverted"]["drift"] == xr["status"]["drift"]
    assert ready(rendered) == "True"


def test_a_write_that_failed_changes_nothing(render):
    xr = example("Manage")
    req = request(render, xr)
    before = render(KIND, xr, [answered(req, "transform-set-transport")], DEVICES)
    xr["status"] = status(before)
    rendered = render(
        KIND, xr, [answered(req, "transform-set-transport", "PATCH", 409)], DEVICES
    )
    assert status(rendered) == xr["status"]
    assert ready(rendered) == "False"
