"""Ikev2Policy: its name, its modes, the check its Request observes with on the router's
recorded answers, and the status it makes of them."""

import json
from functools import partial

import pytest
from conftest import EXAMPLES, IOSXE, check, in_namespace, ready, recorded, status
from conftest import answered as _answered

KIND = "ikev2policy"
XR = "r1--classical-policy--17d97755"
DEVICES = [in_namespace(p) for p in EXAMPLES if p.parent.name == "device"]
answered = partial(_answered, KIND)


def example(policy=None, name=XR):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    xr["metadata"]["name"] = name
    # No `after`: the requests are composed at once.
    del xr["spec"]["after"]
    if policy:
        xr["spec"]["managementPolicy"] = policy
    else:
        del xr["spec"]["managementPolicy"]
    return xr


def thin(name="CLASSICAL-POLICY", xr_name=XR):
    """An object as Step 3 imports it: deviceRef and name, no mode."""
    return {
        "apiVersion": "iosxe.netclab.dev/v1alpha1",
        "kind": "Ikev2Policy",
        "metadata": {"name": xr_name, "namespace": "lab"},
        "spec": {"deviceRef": {"name": "r1"}, "name": name},
    }


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("CLASSICAL-POLICY", "r1--classical-policy--17d97755"),
        # Punctuation at the ends goes, a run of it inside is one dash.
        ("__A..b__", "r1--a-b--"),
    ],
)
def test_an_object_under_another_name_composes_nothing(render, name, want):
    xr = thin(name, "my-policy")
    rendered = render(KIND, xr, required=DEVICES)
    assert rendered.resources == {}
    wants = rendered.composite["status"]["wantsName"]
    assert wants.startswith(want) and len(wants) <= 63
    assert ready(rendered) == "False"
    xr["metadata"]["name"] = wants
    assert list(render(KIND, xr, required=DEVICES).resources) == ["policy"]


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
    request = render(KIND, example(policy), required=DEVICES).resources["policy"]
    assert request["spec"]["managementPolicies"] == policies
    mappings = request["spec"]["forProvider"]["mappings"]
    assert [
        (m["action"], m["method"]) for m in mappings if m["action"] != "OBSERVE"
    ] == writes


def test_manage_patches_a_merge_on_native(render):
    request = render(KIND, example("Manage"), required=DEVICES).resources["policy"]
    for_provider = request["spec"]["forProvider"]
    policy = recorded(KIND, "policy-applied")["body"]["Cisco-IOS-XE-crypto:policy"]
    assert json.loads(for_provider["payload"]["body"]) == {
        "Cisco-IOS-XE-native:native": {
            "crypto": {"Cisco-IOS-XE-crypto:ikev2": {"policy": policy}}
        }
    }
    urls = {m["url"] for m in for_provider["mappings"] if m["action"] != "OBSERVE"}
    assert urls == {'"https://172.18.0.101/restconf/data/Cisco-IOS-XE-native:native"'}


def test_full_control_puts_what_the_router_then_returns(render):
    request = render(KIND, example("FullControl"), required=DEVICES).resources["policy"]
    body = request["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "policy-applied")["body"]


@pytest.mark.parametrize(
    ("state", "manage", "full_control"),
    [
        ("policy-applied", True, True),
        # Beyond the spec: Manage leaves it, FullControl takes it off.
        ("policy-extra-proposal", True, False),
        ("policy-with-match", True, False),
        # The spec's proposal not on the router.
        ("policy-other-proposal", False, False),
        ("policy-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, manage, full_control):
    for policy, expected in [("Manage", manage), ("FullControl", full_control)]:
        request = render(KIND, example(policy), required=DEVICES).resources["policy"]
        assert (
            check(request, "expectedResponseCheck", recorded(KIND, state)) is expected
        )


@pytest.fixture(scope="module")
def after_get(render):
    """The XR rendered with its Request answered by a GET of the router in `state`."""

    def _after_get(xr, state):
        request = render(KIND, xr, required=DEVICES).resources["policy"]
        return render(KIND, xr, [answered(request, state)], DEVICES)

    return _after_get


def test_a_thin_object_shows_the_router_in_the_shape_of_the_spec(after_get):
    rendered = after_get(thin(), "policy-applied")
    assert status(rendered) == {
        "observed": {"proposals": ["CLASSICAL-PROPOSAL"]},
        "drift": [],
        "extra": [],
    }
    assert ready(rendered) == "True"


def test_a_block_gone_from_the_router_is_not_ready(after_get):
    xr = thin()
    xr["status"] = {"observed": {"proposals": ["X"]}, "drift": [], "extra": []}
    rendered = after_get(xr, "policy-absent")
    assert "observed" not in status(rendered)
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "state", "drift", "extra", "is_ready"),
    [
        (
            "Manage",
            "policy-extra-proposal",
            [],
            [{"field": "proposals", "device": ["default"]}],
            "True",
        ),
        (
            "FullControl",
            "policy-extra-proposal",
            [],
            [{"field": "proposals", "device": ["default"]}],
            "False",
        ),
        # A field the spec cannot hold: compared in FullControl alone.
        ("Manage", "policy-with-match", [], [], "True"),
        (
            "FullControl",
            "policy-with-match",
            [],
            [{"field": "match", "device": ['{"fvrf":{"any":[null]}}']}],
            "False",
        ),
        (
            None,
            "policy-other-proposal",
            [
                {
                    "field": "proposals",
                    "device": ["default"],
                    "spec": ["CLASSICAL-PROPOSAL"],
                }
            ],
            [{"field": "proposals", "device": ["default"]}],
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
    request = render(KIND, xr, required=DEVICES).resources["policy"]
    before = render(KIND, xr, [answered(request, "policy-other-proposal")], DEVICES)
    xr["status"] = status(before)
    rendered = render(
        KIND, xr, [answered(request, "policy-other-proposal", "PATCH", 204)], DEVICES
    )
    assert status(rendered)["drift"] == []
    assert status(rendered)["reverted"]["drift"] == xr["status"]["drift"]
    assert ready(rendered) == "True"


def test_a_write_that_failed_changes_nothing(render):
    xr = example("Manage")
    request = render(KIND, xr, required=DEVICES).resources["policy"]
    before = render(KIND, xr, [answered(request, "policy-other-proposal")], DEVICES)
    xr["status"] = status(before)
    rendered = render(
        KIND, xr, [answered(request, "policy-other-proposal", "PATCH", 409)], DEVICES
    )
    assert status(rendered) == xr["status"]
    assert ready(rendered) == "False"
