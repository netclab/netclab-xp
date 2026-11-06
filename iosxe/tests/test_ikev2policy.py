"""Ikev2Policy: its name, its modes, the check its Request observes with on the router's
recorded answers, and the status it makes of them."""

import json
from functools import partial

import pytest
from conftest import (
    DEVICES,
    IOSXE,
    check,
    devices,
    in_namespace,
    ready,
    recorded,
    requests,
    status,
)
from conftest import answered as _answered

KIND = "ikev2policy"
XR = "r1--classical-policy--17d97755"
answered = partial(_answered, KIND)


def example(policy=None, name=XR, fvrf=None):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    xr["metadata"]["name"] = name
    # No `after`: the requests are composed at once.
    del xr["spec"]["after"]
    if policy:
        xr["spec"]["managementPolicy"] = policy
    else:
        del xr["spec"]["managementPolicy"]
    if fvrf:
        xr["spec"]["fvrf"] = fvrf
    return xr


# The Devices, listing the VRF the examples with an fVRF name.
WAN = devices(["WAN"])


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
    assert requests(render(KIND, xr, required=DEVICES).resources) == ["policy"]


@pytest.mark.parametrize(
    ("policy", "policies", "writes"),
    [
        (None, ["Observe"], []),
        (
            "Merge",
            ["Observe", "Create", "Update"],
            [("CREATE", "PATCH"), ("UPDATE", "PATCH")],
        ),
        (
            "Replace",
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


def test_merge_sends_the_patch_the_router_merged(render):
    request = render(KIND, example("Merge"), required=DEVICES).resources["policy"]
    for_provider = request["spec"]["forProvider"]
    sent = recorded(KIND, "policy-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


def test_replace_puts_what_the_router_then_returns(render):
    request = render(KIND, example("Replace"), required=DEVICES).resources["policy"]
    body = request["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "policy-applied")["body"]


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("policy-applied", True, True),
        # Beyond the spec: Merge leaves it, Replace takes it off.
        ("policy-extra-proposal", True, False),
        ("policy-with-match", True, False),
        # Merge's PATCH over `default` alone, merged by the router.
        ("policy-patched", True, False),
        # The spec's proposal not on the router.
        ("policy-other-proposal", False, False),
        ("policy-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
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


def test_a_section_gone_from_the_router_is_not_ready(after_get):
    xr = thin()
    xr["status"] = {"observed": {"proposals": ["X"]}, "drift": [], "extra": []}
    rendered = after_get(xr, "policy-absent")
    assert "observed" not in status(rendered)
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "state", "drift", "extra", "is_ready"),
    [
        (
            "Merge",
            "policy-extra-proposal",
            [],
            [{"field": "proposals", "device": ["default"]}],
            "True",
        ),
        (
            "Replace",
            "policy-extra-proposal",
            [],
            [{"field": "proposals", "device": ["default"]}],
            "False",
        ),
        (
            "Merge",
            "policy-patched",
            [],
            [{"field": "proposals", "device": ["default"]}],
            "True",
        ),
        # A front-door VRF the spec leaves out: compared in Replace alone.
        ("Merge", "policy-with-match", [], [], "True"),
        (
            "Replace",
            "policy-with-match",
            [],
            [{"field": "fvrf", "device": ["any"]}],
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
    xr = example("Merge")
    request = render(KIND, xr, required=DEVICES).resources["policy"]
    before = render(KIND, xr, [answered(request, "policy-other-proposal")], DEVICES)
    xr["status"] = status(before)
    code = recorded(KIND, "policy-patch")["statusCode"]
    rendered = render(
        KIND, xr, [answered(request, "policy-other-proposal", "PATCH", code)], DEVICES
    )
    assert status(rendered)["drift"] == []
    assert status(rendered)["reverted"]["drift"] == xr["status"]["drift"]
    assert ready(rendered) == "True"


def test_a_write_that_failed_changes_nothing(render):
    xr = example("Merge")
    request = render(KIND, xr, required=DEVICES).resources["policy"]
    before = render(KIND, xr, [answered(request, "policy-other-proposal")], DEVICES)
    xr["status"] = status(before)
    rendered = render(
        KIND, xr, [answered(request, "policy-other-proposal", "PATCH", 409)], DEVICES
    )
    assert status(rendered) == xr["status"]
    assert ready(rendered) == "False"


def test_merge_sends_the_fvrf_the_router_merged(render):
    xr = example("Merge", fvrf="WAN")
    for_provider = render(KIND, xr, required=WAN).resources["policy"]["spec"][
        "forProvider"
    ]
    sent = recorded(KIND, "policy-fvrf-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]


@pytest.mark.parametrize(
    ("fvrf", "state"), [("WAN", "policy-fvrf-wan"), ("any", "policy-with-match")]
)
def test_replace_puts_the_fvrf_the_router_then_returns(render, fvrf, state):
    xr = example("Replace", fvrf=fvrf)
    body = render(KIND, xr, required=WAN).resources["policy"]["spec"]["forProvider"][
        "payload"
    ]["body"]
    assert json.loads(body) == recorded(KIND, state)["body"]


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("policy-fvrf-wan", True, True),
        ("policy-fvrf-patched", True, True),
        # A match beyond the fVRF: Merge leaves it, Replace takes it off.
        ("policy-fvrf-and-address", True, False),
        # Another fVRF, or none.
        ("policy-with-match", False, False),
        ("policy-applied", False, False),
    ],
)
def test_check_with_an_fvrf(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
        xr = example(policy, fvrf="WAN")
        request = render(KIND, xr, required=WAN).resources["policy"]
        assert (
            check(request, "expectedResponseCheck", recorded(KIND, state)) is expected
        )


@pytest.mark.parametrize(
    ("policy", "state", "observed", "drift", "extra", "is_ready"),
    [
        ("Merge", "policy-fvrf-wan", "WAN", [], [], "True"),
        (
            "Merge",
            "policy-with-match",
            "any",
            [{"field": "fvrf", "device": ["any"], "spec": ["WAN"]}],
            [],
            "False",
        ),
        (
            "Merge",
            "policy-applied",
            None,
            [{"field": "fvrf", "device": [], "spec": ["WAN"]}],
            [],
            "False",
        ),
        ("Merge", "policy-fvrf-and-address", "WAN", [], [], "True"),
        (
            "Replace",
            "policy-fvrf-and-address",
            "WAN",
            [],
            [{"field": "match", "device": ['{"address":{"local-ip":["10.0.12.1"]}}']}],
            "False",
        ),
    ],
)
def test_the_fvrf_in_status(render, policy, state, observed, drift, extra, is_ready):
    xr = example(policy, fvrf="WAN")
    request = render(KIND, xr, required=WAN).resources["policy"]
    rendered = render(KIND, xr, [answered(request, state)], WAN)
    assert status(rendered)["observed"].get("fvrf") == observed
    assert status(rendered)["drift"] == drift
    assert status(rendered)["extra"] == extra
    assert ready(rendered) == is_ready


def test_a_vrf_the_device_does_not_list_holds_the_policy_back(render):
    xr = example("Replace", fvrf="WAN")
    rendered = render(KIND, xr, required=devices(["OTHER"]))
    assert requests(rendered.resources) == []
    assert status(rendered)["missingVrfs"] == ["WAN"]
    assert ready(rendered) == "False"
    listed = render(KIND, xr, required=WAN)
    assert requests(listed.resources) == ["policy"]
    assert "missingVrfs" not in status(listed)


def test_any_is_no_vrf_to_wait_on(render):
    rendered = render(KIND, example("Replace", fvrf="any"), required=devices([]))
    assert requests(rendered.resources) == ["policy"]


def test_once_composed_a_missing_vrf_holds_nothing_back(render):
    xr = example("Replace", fvrf="WAN")
    request = render(KIND, xr, required=WAN).resources["policy"]
    rendered = render(
        KIND, xr, [answered(request, "policy-fvrf-wan")], devices(["OTHER"])
    )
    assert requests(rendered.resources) == ["policy"]
    assert status(rendered)["missingVrfs"] == ["WAN"]
