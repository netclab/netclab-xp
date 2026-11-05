"""Ikev2Profile: its name, its modes, the checks its Requests observe with on the router's
recorded answers, the RPC that writes `keyring ppk` with its mark, and the status."""

import json
from functools import partial

import pytest
from conftest import (
    DEVICES,
    IOSXE,
    check,
    in_namespace,
    observed,
    ready,
    recorded,
    requests,
    status,
)
from conftest import answered as _answered

KIND = "ikev2profile"
XR = "r1--classical-profile--cdf1f733"
answered = partial(_answered, KIND)


def example(policy=None, drop=()):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    # No `after`: the requests are composed at once.
    del xr["spec"]["after"]
    if policy:
        xr["spec"]["managementPolicy"] = policy
    else:
        del xr["spec"]["managementPolicy"]
    for field in drop:
        del xr["spec"][field]
    return xr


def thin(name="CLASSICAL-PROFILE", xr_name=XR):
    """An object as Step 3 imports it: deviceRef and name, no mode."""
    return {
        "apiVersion": "iosxe.netclab.dev/v1alpha1",
        "kind": "Ikev2Profile",
        "metadata": {"name": xr_name, "namespace": "lab"},
        "spec": {"deviceRef": {"name": "r1"}, "name": name},
    }


def first(render, xr):
    """What the XR composes before anything is observed."""
    return render(KIND, xr, required=DEVICES).resources


def seen(render, xr, profile="profile-applied", mark="ppk-mark-absent"):
    """The XR rendered with the profile's GET in `profile` and the mark's in `mark`, and
    the RPC, where it composes one, answered with the same mark."""
    resources = first(render, xr)
    before = [
        answered(resources["profile"], profile),
        answered(resources["ppk-mark"], mark),
    ]
    rendered = render(KIND, xr, before, DEVICES)
    if "ppk" not in rendered.resources:
        return rendered
    return render(
        KIND, xr, [*before, answered(rendered.resources["ppk"], mark)], DEVICES
    )


def test_an_object_under_another_name_composes_nothing(render):
    xr = thin(xr_name="my-profile")
    rendered = render(KIND, xr, required=DEVICES)
    assert rendered.resources == {}
    assert rendered.composite["status"]["wantsName"] == XR
    assert ready(rendered) == "False"
    xr["metadata"]["name"] = XR
    assert requests(first(render, xr)) == ["ppk-mark", "profile"]


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
    spec = first(render, example(policy))["profile"]["spec"]
    assert spec["managementPolicies"] == policies
    assert [
        (m["action"], m["method"])
        for m in spec["forProvider"]["mappings"]
        if m["action"] != "OBSERVE"
    ] == writes


def test_manage_sends_the_patch_the_router_merged(render):
    for_provider = first(render, example("Manage"))["profile"]["spec"]["forProvider"]
    sent = recorded(KIND, "profile-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


def test_full_control_puts_what_the_router_then_returns(render):
    for_provider = first(render, example("FullControl"))["profile"]["spec"][
        "forProvider"
    ]
    body = json.loads(for_provider["payload"]["body"])
    assert body == recorded(KIND, "profile-applied")["body"]


@pytest.mark.parametrize(
    ("state", "manage", "full_control"),
    [
        ("profile-applied", True, True),
        # The router leaves out a host's mask after some writes.
        ("profile-no-mask", True, True),
        # Beyond the spec: Manage leaves it, FullControl takes it off.
        ("profile-described", True, False),
        ("profile-extra-address", True, False),
        # Manage's PATCH over another address and a description, merged by the router.
        ("profile-patched", True, False),
        # A value of the spec the router lacks.
        ("profile-other-address", False, False),
        ("profile-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, manage, full_control):
    for policy, expected in [("Manage", manage), ("FullControl", full_control)]:
        profile = first(render, example(policy))["profile"]
        assert (
            check(profile, "expectedResponseCheck", recorded(KIND, state)) is expected
        )


@pytest.fixture(scope="module")
def rpc(render):
    """The RPC the XR in `policy` composes once its profile's Request is Ready, with the
    mark the read last found in `mark`; None when it composes none."""

    def _rpc(policy, mark="ppk-mark-absent", drop=()):
        xr = example(policy, drop)
        resources = first(render, xr)
        before = [
            observed(resources["profile"], True),
            answered(resources["ppk-mark"], mark),
        ]
        return render(KIND, xr, before, DEVICES).resources.get("ppk")

    return _rpc


def test_taking_over_writes_the_line_and_its_mark_and_clears_nothing(rpc):
    for_provider = rpc("Manage")["spec"]["forProvider"]
    sent = recorded(KIND, "ppk-rpc")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = {m["action"]: m for m in for_provider["mappings"]}
    assert (writes["CREATE"]["method"], json.loads(writes["CREATE"]["url"])) == (
        sent["method"],
        sent["url"],
    )
    # Manage never removes the line.
    assert "REMOVE" not in writes


def test_a_changed_ppk_keyring_clears_the_peers_sas(rpc):
    body = json.loads(
        rpc("FullControl", "ppk-mark-other")["spec"]["forProvider"]["payload"]["body"]
    )
    clis = body["Cisco-IOS-XE-cli-rpc:input"]["config-clis"].splitlines()
    assert clis[-1] == "do clear crypto ikev2 sa remote 10.0.23.2"


def test_full_control_removes_the_line_its_mark_and_the_sas(rpc):
    mappings = rpc("FullControl")["spec"]["forProvider"]["mappings"]
    remove = next(m for m in mappings if m["action"] == "REMOVE")
    clis = json.loads(remove["body"])["Cisco-IOS-XE-cli-rpc:input"]["config-clis"]
    assert clis.splitlines() == [
        "crypto ikev2 profile CLASSICAL-PROFILE",
        " no keyring ppk",
        " exit",
        "no event manager environment netclab-96580d81",
        "do clear crypto ikev2 sa remote 10.0.23.2",
    ]


@pytest.mark.parametrize(
    ("policy", "drop", "composed"),
    [
        ("Manage", (), True),
        ("FullControl", (), True),
        # Observe writes nothing; without a PPK keyring there is nothing to write.
        (None, (), False),
        ("FullControl", ("ppkKeyring",), False),
    ],
)
def test_the_rpc_is_composed_to_write_a_ppk_keyring(rpc, policy, drop, composed):
    assert (rpc(policy, drop=drop) is not None) is composed


@pytest.mark.parametrize("previous", ["Manage", "FullControl"])
def test_back_in_observe_the_rpc_stays_and_only_reads(render, rpc, previous):
    # Dropped, an RPC composed in FullControl would be deleted with its REMOVE, and the
    # line and its mark taken off the router.
    xr = example(None)
    resources = first(render, xr)
    before = [
        observed(resources["profile"], True),
        observed(resources["ppk-mark"], True),
        observed(rpc(previous), True),
    ]
    spec = render(KIND, xr, before, DEVICES).resources["ppk"]["spec"]
    assert spec["managementPolicies"] == ["Observe"]
    assert spec["forProvider"] == rpc(previous)["spec"]["forProvider"]


def test_the_rpc_waits_for_the_profile(render):
    xr = example("FullControl")
    resources = first(render, xr)
    assert requests(resources) == ["ppk-mark", "profile"]
    before = [
        observed(resources["profile"], False),
        observed(resources["ppk-mark"], True),
    ]
    assert "ppk" not in render(KIND, xr, before, DEVICES).resources


@pytest.mark.parametrize(("policy", "held"), [("Manage", False), ("FullControl", True)])
def test_full_control_deletes_the_profile_only_after_the_line(render, policy, held):
    # The line's removal enters the profile, which would make it again once deleted.
    xr = example(policy)
    resources = first(render, xr)
    before = [
        observed(resources["profile"], True),
        observed(resources["ppk-mark"], True),
    ]
    before.append(observed(render(KIND, xr, before, DEVICES).resources["ppk"], True))
    usage = render(KIND, xr, before, DEVICES).resources.get("profile-by-ppk")
    assert (usage is not None) is held
    if held:
        assert usage["spec"]["of"]["resourceRef"] == {
            "name": before[0]["metadata"]["name"]
        }
        assert usage["spec"]["by"]["resourceRef"] == {
            "name": before[2]["metadata"]["name"]
        }
        assert usage["spec"]["replayDeletion"] is True


@pytest.mark.parametrize(
    ("mark", "written"),
    [("ppk-mark-applied", True), ("ppk-mark-other", False), ("ppk-mark-absent", False)],
)
def test_the_rpc_checks_its_mark(rpc, mark, written):
    assert (
        check(rpc("FullControl"), "expectedResponseCheck", recorded(KIND, mark))
        is written
    )


@pytest.mark.parametrize(
    ("mark", "observed_"),
    [
        (
            "ppk-mark-absent",
            {"remoteAddresses": ["10.0.23.2"], "keyring": "CLASSICAL-KEYRING"},
        ),
        # The PPK keyring only where the package wrote it.
        (
            "ppk-mark-applied",
            {
                "remoteAddresses": ["10.0.23.2"],
                "keyring": "CLASSICAL-KEYRING",
                "ppkKeyring": "CLASSICAL-KEYRING",
            },
        ),
    ],
)
def test_a_thin_object_shows_the_router_in_the_shape_of_the_spec(
    render, mark, observed_
):
    rendered = seen(render, thin(), mark=mark)
    assert status(rendered) == {"observed": observed_, "drift": [], "extra": []}
    assert ready(rendered) == "True"


@pytest.mark.parametrize(
    ("mark", "shown"),
    [("ppk-mark-absent", None), ("ppk-mark-other", "OLD-KEYRING")],
)
def test_the_ppk_keyring_is_shown_from_its_mark_not_the_spec(render, mark, shown):
    rendered = seen(render, example("FullControl"), mark=mark)
    assert status(rendered)["observed"].get("ppkKeyring") == shown


def test_a_section_gone_from_the_router_is_not_ready(render):
    xr = thin()
    xr["status"] = {"observed": {"keyring": "X"}, "drift": [], "extra": []}
    rendered = seen(render, xr, "profile-absent")
    assert "observed" not in status(rendered)
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "drop", "profile", "mark", "drift", "extra", "is_ready"),
    [
        # Not Ready until the mark is there, so what waits on it waits for the line.
        (
            "FullControl",
            (),
            "profile-applied",
            "ppk-mark-absent",
            [{"field": "ppkKeyring", "device": [], "spec": ["CLASSICAL-KEYRING"]}],
            [],
            "False",
        ),
        ("FullControl", (), "profile-applied", "ppk-mark-applied", [], [], "True"),
        (
            "Manage",
            (),
            "profile-applied",
            "ppk-mark-other",
            [
                {
                    "field": "ppkKeyring",
                    "device": ["OLD-KEYRING"],
                    "spec": ["CLASSICAL-KEYRING"],
                }
            ],
            [],
            "False",
        ),
        # A PPK keyring the spec leaves out: compared in FullControl alone.
        (
            "Manage",
            ("ppkKeyring",),
            "profile-applied",
            "ppk-mark-applied",
            [],
            [],
            "True",
        ),
        (
            "FullControl",
            ("ppkKeyring",),
            "profile-applied",
            "ppk-mark-applied",
            [],
            [{"field": "ppkKeyring", "device": ["CLASSICAL-KEYRING"]}],
            "False",
        ),
        # A line the spec cannot hold.
        ("Manage", (), "profile-described", "ppk-mark-applied", [], [], "True"),
        (
            "FullControl",
            (),
            "profile-described",
            "ppk-mark-applied",
            [],
            [{"field": "description", "device": ['"made by hand"']}],
            "False",
        ),
        (
            "Manage",
            (),
            "profile-extra-address",
            "ppk-mark-applied",
            [],
            [{"field": "remoteAddresses", "device": ["10.0.12.2"]}],
            "True",
        ),
        (
            None,
            (),
            "profile-other-address",
            "ppk-mark-applied",
            [
                {
                    "field": "remoteAddresses",
                    "device": ["10.0.12.9"],
                    "spec": ["10.0.23.2"],
                }
            ],
            [{"field": "remoteAddresses", "device": ["10.0.12.9"]}],
            "False",
        ),
    ],
)
def test_drift_and_extra_follow_the_mode(
    render, policy, drop, profile, mark, drift, extra, is_ready
):
    rendered = seen(render, example(policy, drop), profile, mark)
    assert status(rendered)["drift"] == drift
    assert status(rendered)["extra"] == extra
    assert ready(rendered) == is_ready


def test_a_write_that_succeeded_records_what_it_put_back(render):
    # The profile's write alone: no PPK keyring, so no RPC.
    xr = example("Manage", ("ppkKeyring",))
    resources = first(render, xr)
    mark = answered(resources["ppk-mark"], "ppk-mark-applied")
    before = render(
        KIND,
        xr,
        [answered(resources["profile"], "profile-other-address"), mark],
        DEVICES,
    )
    xr["status"] = status(before)
    code = recorded(KIND, "profile-patch")["statusCode"]
    after = answered(resources["profile"], "profile-other-address", "PATCH", code)
    rendered = render(KIND, xr, [after, mark], DEVICES)
    assert status(rendered)["drift"] == []
    assert status(rendered)["reverted"]["drift"] == xr["status"]["drift"]
    assert ready(rendered) == "True"


def test_a_write_that_failed_changes_nothing(render):
    xr = example("Manage", ("ppkKeyring",))
    resources = first(render, xr)
    mark = answered(resources["ppk-mark"], "ppk-mark-applied")
    before = render(
        KIND,
        xr,
        [answered(resources["profile"], "profile-other-address"), mark],
        DEVICES,
    )
    xr["status"] = status(before)
    after = answered(resources["profile"], "profile-other-address", "PATCH", 409)
    rendered = render(KIND, xr, [after, mark], DEVICES)
    assert status(rendered) == xr["status"]
    assert ready(rendered) == "False"
