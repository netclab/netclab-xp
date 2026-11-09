"""Ikev2Profile: its name, its modes, the checks its Requests observe with on the router's
recorded answers, the RPC that writes `keyring ppk` with its mark, and the status."""

import json
from functools import partial

import pytest
from conftest import (
    DEVICES,
    IOSXE,
    check,
    devices,
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


def example(policy=None, drop=(), fvrf=None):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    # No `after`: the requests are composed at once.
    del xr["spec"]["after"]
    if policy:
        xr["spec"]["managementPolicy"] = policy
    else:
        del xr["spec"]["managementPolicy"]
    for field in drop:
        del xr["spec"][field]
    if fvrf:
        xr["spec"]["fvrf"] = fvrf
    return xr


# The Devices, listing the VRF the examples with an fVRF name.
WAN = devices(["WAN"])


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


def seen(render, xr, profile="profile-applied", mark="ppk-mark-absent", synced=True):
    """The XR rendered with the profile's GET in `profile` and the mark's in `mark`, the
    mark's Request `synced` or not, and the RPC, where it composes one, answered with the
    same mark."""
    resources = first(render, xr)
    before = [
        answered(resources["profile"], profile),
        answered(resources["ppk-mark"], mark, synced=synced),
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
    spec = first(render, example(policy))["profile"]["spec"]
    assert spec["managementPolicies"] == policies
    assert [
        (m["action"], m["method"])
        for m in spec["forProvider"]["mappings"]
        if m["action"] != "OBSERVE"
    ] == writes


def test_merge_sends_the_patch_the_router_merged(render):
    for_provider = first(render, example("Merge"))["profile"]["spec"]["forProvider"]
    sent = recorded(KIND, "profile-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


def test_replace_puts_what_the_router_then_returns(render):
    for_provider = first(render, example("Replace"))["profile"]["spec"]["forProvider"]
    body = json.loads(for_provider["payload"]["body"])
    assert body == recorded(KIND, "profile-applied")["body"]


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("profile-applied", True, True),
        # The router leaves out a host's mask after some writes.
        ("profile-no-mask", True, True),
        # Beyond the spec: Merge leaves it, Replace takes it off.
        ("profile-described", True, False),
        ("profile-extra-address", True, False),
        # Merge's PATCH over another address and a description, merged by the router.
        ("profile-patched", True, False),
        # A value of the spec the router lacks.
        ("profile-other-address", False, False),
        ("profile-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
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
    for_provider = rpc("Merge")["spec"]["forProvider"]
    sent = recorded(KIND, "ppk-rpc")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = {m["action"]: m for m in for_provider["mappings"]}
    assert (writes["CREATE"]["method"], json.loads(writes["CREATE"]["url"])) == (
        sent["method"],
        sent["url"],
    )
    # Merge never removes the line.
    assert "REMOVE" not in writes


def test_a_changed_ppk_keyring_clears_the_peers_sas(rpc):
    body = json.loads(
        rpc("Replace", "ppk-mark-other")["spec"]["forProvider"]["payload"]["body"]
    )
    clis = body["Cisco-IOS-XE-cli-rpc:input"]["config-clis"].splitlines()
    assert clis[-1] == "do clear crypto ikev2 sa remote 10.0.23.2"


def test_replace_removes_the_line_its_mark_and_the_sas(rpc):
    mappings = rpc("Replace")["spec"]["forProvider"]["mappings"]
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
        ("Merge", (), True),
        ("Replace", (), True),
        # Observe writes nothing; without a PPK keyring there is nothing to write.
        (None, (), False),
        ("Replace", ("ppkKeyring",), False),
    ],
)
def test_the_rpc_is_composed_to_write_a_ppk_keyring(rpc, policy, drop, composed):
    assert (rpc(policy, drop=drop) is not None) is composed


@pytest.mark.parametrize("previous", ["Merge", "Replace"])
def test_back_in_observe_the_rpc_stays_and_only_reads(render, rpc, previous):
    # Dropped, an RPC composed in Replace would be deleted with its REMOVE, and the
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
    xr = example("Replace")
    resources = first(render, xr)
    assert requests(resources) == ["ppk-mark", "profile"]
    before = [
        observed(resources["profile"], False),
        observed(resources["ppk-mark"], True),
    ]
    assert "ppk" not in render(KIND, xr, before, DEVICES).resources


@pytest.mark.parametrize(("policy", "held"), [("Merge", False), ("Replace", True)])
def test_replace_deletes_the_profile_only_after_the_line(render, policy, held):
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
        check(rpc("Replace"), "expectedResponseCheck", recorded(KIND, mark)) is written
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
    rendered = seen(render, example("Replace"), mark=mark)
    assert status(rendered)["observed"].get("ppkKeyring") == shown


@pytest.mark.parametrize(
    ("synced", "extra", "is_ready"),
    [
        (True, [{"field": "ppkKeyring", "device": ["CLASSICAL-KEYRING"]}], "False"),
        # The mark taken off: its GET answered 404, the body is still the last 200's.
        (False, [], "True"),
    ],
)
def test_a_mark_read_before_a_404_is_not_read_again(render, synced, extra, is_ready):
    rendered = seen(
        render,
        example("Replace", ("ppkKeyring",)),
        mark="ppk-mark-applied",
        synced=synced,
    )
    assert status(rendered)["extra"] == extra
    assert ready(rendered) == is_ready


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
            "Replace",
            (),
            "profile-applied",
            "ppk-mark-absent",
            [{"field": "ppkKeyring", "device": [], "spec": ["CLASSICAL-KEYRING"]}],
            [],
            "False",
        ),
        ("Replace", (), "profile-applied", "ppk-mark-applied", [], [], "True"),
        (
            "Merge",
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
        # A PPK keyring the spec leaves out: compared in Replace alone.
        (
            "Merge",
            ("ppkKeyring",),
            "profile-applied",
            "ppk-mark-applied",
            [],
            [],
            "True",
        ),
        (
            "Replace",
            ("ppkKeyring",),
            "profile-applied",
            "ppk-mark-applied",
            [],
            [{"field": "ppkKeyring", "device": ["CLASSICAL-KEYRING"]}],
            "False",
        ),
        # A line the spec cannot hold.
        ("Merge", (), "profile-described", "ppk-mark-applied", [], [], "True"),
        (
            "Replace",
            (),
            "profile-described",
            "ppk-mark-applied",
            [],
            [{"field": "description", "device": ['"made by hand"']}],
            "False",
        ),
        (
            "Merge",
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
    xr = example("Merge", ("ppkKeyring",))
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
    xr = example("Merge", ("ppkKeyring",))
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


def with_fvrf(policy, fvrf="WAN"):
    """The example with an fVRF and no PPK keyring, whose RPC these tests leave aside."""
    return example(policy, ("ppkKeyring",), fvrf)


def test_merge_sends_the_fvrf_the_router_merged(render):
    body = render(KIND, with_fvrf("Merge"), required=WAN).resources["profile"]["spec"][
        "forProvider"
    ]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "profile-fvrf-patch")["request"]["body"]


@pytest.mark.parametrize(
    ("fvrf", "state"), [("WAN", "profile-fvrf-wan"), ("any", "profile-fvrf-any")]
)
def test_replace_puts_the_fvrf_the_router_then_returns(render, fvrf, state):
    body = render(KIND, with_fvrf("Replace", fvrf), required=WAN).resources["profile"][
        "spec"
    ]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, state)["body"]


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("profile-fvrf-wan", True, True),
        ("profile-fvrf-patched", True, True),
        # Another fVRF, or none.
        ("profile-fvrf-any", False, False),
        ("profile-applied", False, False),
    ],
)
def test_check_with_an_fvrf(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
        request = render(KIND, with_fvrf(policy), required=WAN).resources["profile"]
        assert (
            check(request, "expectedResponseCheck", recorded(KIND, state)) is expected
        )


@pytest.mark.parametrize(
    ("xr", "state", "observed", "drift", "extra"),
    [
        (with_fvrf("Merge"), "profile-fvrf-wan", "WAN", [], []),
        (
            with_fvrf("Merge"),
            "profile-fvrf-any",
            "any",
            [{"field": "fvrf", "device": ["any"], "spec": ["WAN"]}],
            [],
        ),
        # A front-door VRF the spec leaves out: compared in Replace alone.
        (example("Merge", ("ppkKeyring",)), "profile-fvrf-wan", "WAN", [], []),
        (
            example("Replace", ("ppkKeyring",)),
            "profile-fvrf-wan",
            "WAN",
            [],
            [{"field": "fvrf", "device": ["WAN"]}],
        ),
    ],
)
def test_the_fvrf_in_status(render, xr, state, observed, drift, extra):
    resources = render(KIND, xr, required=WAN).resources
    before = [
        answered(resources["profile"], state),
        answered(resources["ppk-mark"], "ppk-mark-absent"),
    ]
    rendered = render(KIND, xr, before, WAN)
    assert status(rendered)["observed"].get("fvrf") == observed
    assert status(rendered)["drift"] == drift
    assert status(rendered)["extra"] == extra


def test_a_vrf_the_device_does_not_list_holds_the_profile_back(render):
    xr = with_fvrf("Replace")
    rendered = render(KIND, xr, required=devices(["OTHER"]))
    assert requests(rendered.resources) == []
    assert status(rendered)["missingVrfs"] == ["WAN"]
    assert ready(rendered) == "False"
    assert requests(render(KIND, xr, required=WAN).resources) == ["ppk-mark", "profile"]


def test_any_is_no_vrf_to_wait_on(render):
    rendered = render(KIND, with_fvrf("Replace", "any"), required=devices([]))
    assert requests(rendered.resources) == ["ppk-mark", "profile"]
