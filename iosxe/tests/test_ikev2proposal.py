"""Ikev2Proposal: its name, its modes, the check its Request observes with on the router's
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

KIND = "ikev2proposal"
answered = partial(_answered, KIND)
XR = "r1--classical-proposal--3a16aab3"


def example(policy=None, name=XR, **spec):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    xr["metadata"]["name"] = name
    if policy:
        xr["spec"]["managementPolicy"] = policy
    xr["spec"].update(spec)
    return xr


def thin(name="CLASSICAL-PROPOSAL", xr_name=XR):
    """An object as Step 3 imports it: deviceRef and name, no mode."""
    return {
        "apiVersion": "iosxe.netclab.dev/v1alpha1",
        "kind": "Ikev2Proposal",
        "metadata": {"name": xr_name, "namespace": "lab"},
        "spec": {"deviceRef": {"name": "r1"}, "name": name},
    }


@pytest.mark.parametrize(
    ("device", "name", "want"),
    [
        ("r1", "CLASSICAL-PROPOSAL", "r1--classical-proposal--3a16aab3"),
        ("r1", "LEGACY_PROPOSAL", "r1--legacy-proposal--d8cc32e4"),
        # Punctuation at the ends goes, a run of it inside is one dash.
        ("r1", "__A..b__", "r1--a-b--"),
        # Cut so that the whole name fits 63 characters.
        ("r1", "P" * 80, "r1--" + "p" * 49 + "--"),
    ],
)
def test_an_object_under_another_name_composes_nothing(render, device, name, want):
    xr = thin(name, "my-proposal")
    xr["spec"]["deviceRef"]["name"] = device
    rendered = render(KIND, xr, required=DEVICES)
    assert rendered.resources == {}
    wants = rendered.composite["status"]["wantsName"]
    assert wants.startswith(want) and len(wants) <= 63
    assert ready(rendered) == "False"
    # Under the name it wants, the object composes its Request.
    xr["metadata"]["name"] = wants
    assert requests(render(KIND, xr, required=DEVICES).resources) == ["proposal"]


@pytest.mark.parametrize(
    ("policy", "policies", "writes"),
    [
        (None, ["Observe"], []),
        ("Observe", ["Observe"], []),
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
    xr = example(policy)
    if policy is None:
        del xr["spec"]["managementPolicy"]
    request = render(KIND, xr, required=DEVICES).resources["proposal"]["spec"]
    assert request["managementPolicies"] == policies
    mappings = request["forProvider"]["mappings"]
    assert [
        (m["action"], m["method"]) for m in mappings if m["action"] != "OBSERVE"
    ] == writes


def test_manage_sends_the_patch_the_router_merged(render):
    request = render(KIND, example("Merge"), required=DEVICES).resources["proposal"]
    for_provider = request["spec"]["forProvider"]
    sent = recorded(KIND, "proposal-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


def test_replace_puts_what_the_router_then_returns(render):
    request = render(KIND, example("Replace"), required=DEVICES).resources["proposal"]
    body = request["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "proposal-applied")["body"]


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("proposal-applied", True, True),
        # Beyond the spec: Merge leaves it, Replace takes it off.
        ("proposal-extra-encryption", True, False),
        ("proposal-with-prf", True, False),
        # Merge's PATCH over group 19 alone, merged by the router.
        ("proposal-patched", True, False),
        # The spec's values not on the router.
        ("proposal-other-integrity", False, False),
        ("proposal-other-group", False, False),
        ("proposal-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
        request = render(KIND, example(policy), required=DEVICES).resources["proposal"]
        assert (
            check(request, "expectedResponseCheck", recorded(KIND, state)) is expected
        )


@pytest.fixture(scope="module")
def after_get(render):
    """The XR rendered with its Request answered by a GET of the router in `state`."""

    def _after_get(xr, state, method="GET", status=None):
        request = render(KIND, xr, required=DEVICES).resources["proposal"]
        seen = [answered(request, state, method, status)]
        return render(KIND, xr, seen, DEVICES)

    return _after_get


def test_a_thin_object_shows_the_router_in_the_shape_of_the_spec(after_get):
    rendered = after_get(thin(), "proposal-applied")
    assert status(rendered) == {
        "observed": {
            "encryption": ["aes-cbc-256"],
            "integrity": ["sha512"],
            "group": [20],
        },
        "drift": [],
        "extra": [],
    }
    assert ready(rendered) == "True"


def test_a_section_gone_from_the_router_is_not_ready(after_get):
    xr = thin()
    xr["status"] = {
        "observed": {"encryption": ["aes-cbc-256"]},
        "drift": [],
        "extra": [],
    }
    rendered = after_get(xr, "proposal-absent")
    assert "observed" not in status(rendered)
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "state", "drift", "extra", "is_ready"),
    [
        (
            "Merge",
            "proposal-extra-encryption",
            [],
            [{"field": "encryption", "device": ["aes-cbc-128"]}],
            "True",
        ),
        (
            "Replace",
            "proposal-extra-encryption",
            [],
            [{"field": "encryption", "device": ["aes-cbc-128"]}],
            "False",
        ),
        # A field the spec leaves out: compared in Replace alone.
        ("Merge", "proposal-with-prf", [], [], "True"),
        (
            "Replace",
            "proposal-with-prf",
            [],
            [{"field": "prf", "device": ["sha384"]}],
            "False",
        ),
        (
            "Observe",
            "proposal-other-group",
            [{"field": "group", "device": ["19"], "spec": ["20"]}],
            [{"field": "group", "device": ["19"]}],
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
    request = render(KIND, xr, required=DEVICES).resources["proposal"]
    before = render(KIND, xr, [answered(request, "proposal-other-group")], DEVICES)
    xr["status"] = status(before)
    code = recorded(KIND, "proposal-patch")["statusCode"]
    rendered = render(
        KIND, xr, [answered(request, "proposal-other-group", "PATCH", code)], DEVICES
    )
    assert status(rendered)["drift"] == []
    assert status(rendered)["reverted"]["drift"] == xr["status"]["drift"]
    assert ready(rendered) == "True"
    # Seen again before the next GET: the same record, the same time.
    xr["status"] = status(rendered)
    xr["status"]["reverted"]["time"] = "2000-01-01T00:00:00Z"
    again = render(
        KIND, xr, [answered(request, "proposal-other-group", "PATCH", code)], DEVICES
    )
    assert status(again)["reverted"] == xr["status"]["reverted"]


def test_a_write_that_failed_changes_nothing(render):
    xr = example("Merge")
    request = render(KIND, xr, required=DEVICES).resources["proposal"]
    before = render(KIND, xr, [answered(request, "proposal-other-group")], DEVICES)
    xr["status"] = status(before)
    rendered = render(
        KIND, xr, [answered(request, "proposal-other-group", "PATCH", 409)], DEVICES
    )
    assert status(rendered) == xr["status"]
    assert ready(rendered) == "False"
