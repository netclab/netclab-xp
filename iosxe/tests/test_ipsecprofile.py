"""IpsecProfile: its name, its modes, the check its Request observes with on the router's
recorded answers, and the status it makes of them."""

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

KIND = "ipsecprofile"
XR = "r1--classical-ipsec--461c477a"
answered = partial(_answered, KIND)


def example(policy=None):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    # No `after`: the requests are composed at once.
    del xr["spec"]["after"]
    if policy:
        xr["spec"]["managementPolicy"] = policy
    else:
        del xr["spec"]["managementPolicy"]
    return xr


def thin(name="CLASSICAL-IPSEC", xr_name=XR):
    """An object as Step 3 imports it: deviceRef and name, no mode."""
    return {
        "apiVersion": "iosxe.netclab.dev/v1alpha1",
        "kind": "IpsecProfile",
        "metadata": {"name": xr_name, "namespace": "lab"},
        "spec": {"deviceRef": {"name": "r1"}, "name": name},
    }


def request(render, xr):
    return render(KIND, xr, required=DEVICES).resources["profile"]


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("CLASSICAL-IPSEC", "r1--classical-ipsec--461c477a"),
        ("__A..b__", "r1--a-b--"),
    ],
)
def test_an_object_under_another_name_composes_nothing(render, name, want):
    xr = thin(name, "my-ipsec-profile")
    rendered = render(KIND, xr, required=DEVICES)
    assert rendered.resources == {}
    wants = rendered.composite["status"]["wantsName"]
    assert wants.startswith(want) and len(wants) <= 63
    assert ready(rendered) == "False"
    xr["metadata"]["name"] = wants
    assert requests(render(KIND, xr, required=DEVICES).resources) == ["profile"]


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


def test_manage_sends_the_patch_the_router_merged(render):
    for_provider = request(render, example("Manage"))["spec"]["forProvider"]
    sent = recorded(KIND, "profile-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


def test_full_control_puts_what_the_router_then_returns(render):
    body = request(render, example("FullControl"))["spec"]["forProvider"]
    assert (
        json.loads(body["payload"]["body"]) == recorded(KIND, "profile-applied")["body"]
    )


@pytest.mark.parametrize(
    ("state", "manage", "full_control"),
    [
        ("profile-applied", True, True),
        # Beyond the spec: Manage leaves it, FullControl takes it off.
        ("profile-extra-transform-set", True, False),
        ("profile-with-pfs", True, False),
        # Manage's PATCH over OTHER-TS alone, merged by the router.
        ("profile-patched", True, False),
        # A value of the spec the router lacks.
        ("profile-other-transform-set", False, False),
        ("profile-no-ikev2-profile", False, False),
        ("profile-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, manage, full_control):
    for policy, expected in [("Manage", manage), ("FullControl", full_control)]:
        req = request(render, example(policy))
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
            "profile-applied",
            {"transformSets": ["CLASSICAL-TS"], "ikev2Profile": "CLASSICAL-PROFILE"},
        ),
        ("profile-no-ikev2-profile", {"transformSets": ["CLASSICAL-TS"]}),
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
    xr["status"] = {"observed": {"transformSets": ["X"]}, "drift": [], "extra": []}
    rendered = after_get(xr, "profile-absent")
    assert "observed" not in status(rendered)
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "state", "drift", "extra", "is_ready"),
    [
        (
            "Manage",
            "profile-extra-transform-set",
            [],
            [{"field": "transformSets", "device": ["OTHER-TS"]}],
            "True",
        ),
        (
            "FullControl",
            "profile-extra-transform-set",
            [],
            [{"field": "transformSets", "device": ["OTHER-TS"]}],
            "False",
        ),
        # A field the spec cannot hold: compared in FullControl alone.
        ("Manage", "profile-with-pfs", [], [], "True"),
        (
            "FullControl",
            "profile-with-pfs",
            [],
            [{"field": "pfs", "device": ['{"group":"group20"}']}],
            "False",
        ),
        (
            None,
            "profile-no-ikev2-profile",
            [{"field": "ikev2Profile", "device": [], "spec": ["CLASSICAL-PROFILE"]}],
            [],
            "False",
        ),
        (
            None,
            "profile-other-transform-set",
            [
                {
                    "field": "transformSets",
                    "device": ["OTHER-TS"],
                    "spec": ["CLASSICAL-TS"],
                }
            ],
            [{"field": "transformSets", "device": ["OTHER-TS"]}],
            "False",
        ),
    ],
)
def test_drift_and_extra_follow_the_mode(
    after_get, policy, state, drift, extra, is_ready
):
    rendered = after_get(example(policy), state)
    assert status(rendered)["drift"] == drift
    assert status(rendered)["extra"] == extra
    assert ready(rendered) == is_ready


def test_a_write_that_succeeded_records_what_it_put_back(render):
    xr = example("Manage")
    req = request(render, xr)
    before = render(KIND, xr, [answered(req, "profile-no-ikev2-profile")], DEVICES)
    xr["status"] = status(before)
    code = recorded(KIND, "profile-patch")["statusCode"]
    rendered = render(
        KIND, xr, [answered(req, "profile-no-ikev2-profile", "PATCH", code)], DEVICES
    )
    assert status(rendered)["drift"] == []
    assert status(rendered)["reverted"]["drift"] == xr["status"]["drift"]
    assert ready(rendered) == "True"


def test_a_write_that_failed_changes_nothing(render):
    xr = example("Manage")
    req = request(render, xr)
    before = render(KIND, xr, [answered(req, "profile-no-ikev2-profile")], DEVICES)
    xr["status"] = status(before)
    rendered = render(
        KIND, xr, [answered(req, "profile-no-ikev2-profile", "PATCH", 409)], DEVICES
    )
    assert status(rendered) == xr["status"]
    assert ready(rendered) == "False"
