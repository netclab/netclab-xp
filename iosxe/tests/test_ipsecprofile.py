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


def with_pfs(xr, group="group14"):
    xr["spec"]["pfs"] = group
    return xr


def with_sa(xr):
    """The dfbit, window size and lifetime of AWS's sample for CSRv."""
    xr["spec"]["dfbit"] = "clear"
    xr["spec"]["replayWindowSize"] = 128
    xr["spec"]["lifetime"] = 3600
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
    spec = request(render, example(policy))["spec"]
    assert spec["managementPolicies"] == policies
    assert [
        (m["action"], m["method"])
        for m in spec["forProvider"]["mappings"]
        if m["action"] != "OBSERVE"
    ] == writes


@pytest.mark.parametrize(
    ("pfs", "state"), [(None, "profile-patch"), ("group14", "profile-pfs-patch")]
)
def test_merge_sends_the_patch_the_router_merged(render, pfs, state):
    xr = example("Merge")
    if pfs:
        with_pfs(xr, pfs)
    for_provider = request(render, xr)["spec"]["forProvider"]
    sent = recorded(KIND, state)["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


@pytest.mark.parametrize(
    ("pfs", "state"), [(None, "profile-applied"), ("group14", "profile-pfs-applied")]
)
def test_replace_puts_what_the_router_then_returns(render, pfs, state):
    xr = example("Replace")
    if pfs:
        with_pfs(xr, pfs)
    body = request(render, xr)["spec"]["forProvider"]
    assert json.loads(body["payload"]["body"]) == recorded(KIND, state)["body"]


def test_merge_sends_the_security_association_the_router_merged(render):
    for_provider = request(render, with_sa(example("Merge")))["spec"]["forProvider"]
    sent = recorded(KIND, "profile-sa-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]


def test_replace_puts_the_security_association_the_router_then_returns(render):
    for_provider = request(render, with_sa(example("Replace")))["spec"]["forProvider"]
    body = json.loads(for_provider["payload"]["body"])
    returned = recorded(KIND, "profile-sa-applied")["body"]
    # The router gives the lifetime's seconds-case again in the deprecated seconds.
    del returned["Cisco-IOS-XE-crypto:profile"][0]["set"]["security-association"][
        "lifetime"
    ]["seconds"]
    assert body == returned


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("profile-applied", True, True),
        # Beyond the spec: Merge leaves it, Replace takes it off.
        ("profile-extra-transform-set", True, False),
        ("profile-with-pfs", True, False),
        ("profile-sa-applied", True, False),
        # Merge's PATCH over OTHER-TS alone, merged by the router.
        ("profile-patched", True, False),
        # A value of the spec the router lacks.
        ("profile-other-transform-set", False, False),
        ("profile-no-ikev2-profile", False, False),
        ("profile-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
        req = request(render, example(policy))
        assert check(req, "expectedResponseCheck", recorded(KIND, state)) is expected


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("profile-pfs-applied", True, True),
        # `set pfs` alone: group14, given as an empty pfs.
        ("profile-pfs-default", True, True),
        # Merge's PATCH with pfs over the example without it, merged by the router.
        ("profile-pfs-patched", True, True),
        ("profile-with-pfs", False, False),
        ("profile-applied", False, False),
    ],
)
def test_check_compares_the_pfs_group(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
        req = request(render, with_pfs(example(policy)))
        assert check(req, "expectedResponseCheck", recorded(KIND, state)) is expected


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("profile-sa-applied", True, True),
        # Merge's PATCH of both over dfbit set alone, merged by the router.
        ("profile-sa-patched", True, True),
        ("profile-sa-other", False, False),
        # Each field alone: another dfbit; `replay disable` in place of the window size;
        # another lifetime.
        ("profile-sa-dfbit-set", False, False),
        ("profile-sa-replay-disable", False, False),
        ("profile-sa-lifetime-other", False, False),
        # A lifetime in kilobytes beside the spec's: Merge leaves it, Replace takes it off.
        ("profile-sa-kilobytes", True, False),
        ("profile-applied", False, False),
    ],
)
def test_check_compares_the_security_association(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
        req = request(render, with_sa(example(policy)))
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
        (
            "profile-pfs-default",
            {
                "transformSets": ["CLASSICAL-TS"],
                "ikev2Profile": "CLASSICAL-PROFILE",
                "pfs": "group14",
            },
        ),
        (
            "profile-sa-applied",
            {
                "transformSets": ["CLASSICAL-TS"],
                "ikev2Profile": "CLASSICAL-PROFILE",
                "dfbit": "clear",
                "replayWindowSize": 128,
                "lifetime": 3600,
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
    xr["status"] = {"observed": {"transformSets": ["X"]}, "drift": [], "extra": []}
    rendered = after_get(xr, "profile-absent")
    assert "observed" not in status(rendered)
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "state", "drift", "extra", "is_ready"),
    [
        (
            "Merge",
            "profile-extra-transform-set",
            [],
            [{"field": "transformSets", "device": ["OTHER-TS"]}],
            "True",
        ),
        (
            "Replace",
            "profile-extra-transform-set",
            [],
            [{"field": "transformSets", "device": ["OTHER-TS"]}],
            "False",
        ),
        # pfs the spec leaves out: Merge leaves it, Replace takes it off.
        ("Merge", "profile-with-pfs", [], [], "True"),
        (
            "Replace",
            "profile-with-pfs",
            [],
            [{"field": "pfs", "device": ["group20"]}],
            "False",
        ),
        # A security association the spec leaves out: the same.
        ("Merge", "profile-sa-applied", [], [], "True"),
        (
            "Replace",
            "profile-sa-applied",
            [],
            [
                {"field": "dfbit", "device": ["clear"]},
                {"field": "replayWindowSize", "device": ["128"]},
                {"field": "lifetime", "device": ["3600"]},
            ],
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


@pytest.mark.parametrize(
    ("state", "drift"),
    [
        (
            "profile-with-pfs",
            [{"field": "pfs", "device": ["group20"], "spec": ["group14"]}],
        ),
        ("profile-applied", [{"field": "pfs", "device": [], "spec": ["group14"]}]),
        ("profile-pfs-default", []),
    ],
)
def test_a_pfs_group_the_router_lacks_is_drift(after_get, state, drift):
    for policy in ["Merge", "Replace"]:
        rendered = after_get(with_pfs(example(policy)), state)
        assert status(rendered)["drift"] == drift
        assert ready(rendered) == ("False" if drift else "True")


SA_OTHER = [
    {"field": "dfbit", "device": ["set"], "spec": ["clear"]},
    {"field": "replayWindowSize", "device": ["1024"], "spec": ["128"]},
    {"field": "lifetime", "device": ["900"], "spec": ["3600"]},
]
NO_WINDOW = [{"field": "replayWindowSize", "device": [], "spec": ["128"]}]
REPLAY_DISABLE = [
    {"field": "security-association", "device": ['{"replay":{"disable":[null]}}']}
]
KILOBYTES = [
    {"field": "security-association", "device": ['{"lifetime":{"kilobytes":"102400"}}']}
]


@pytest.mark.parametrize(
    ("policy", "state", "drift", "extra"),
    [
        ("Merge", "profile-sa-other", SA_OTHER, []),
        ("Replace", "profile-sa-other", SA_OTHER, []),
        # `replay disable` the spec has no field for: beyond it in Replace alone.
        ("Merge", "profile-sa-replay-disable", NO_WINDOW, []),
        ("Replace", "profile-sa-replay-disable", NO_WINDOW, REPLAY_DISABLE),
        ("Merge", "profile-sa-kilobytes", [], []),
        ("Replace", "profile-sa-kilobytes", [], KILOBYTES),
        # The seconds the router gives the lifetime in again are no field beyond the spec.
        ("Replace", "profile-sa-applied", [], []),
    ],
)
def test_a_security_association_the_router_lacks_is_drift(
    after_get, policy, state, drift, extra
):
    rendered = after_get(with_sa(example(policy)), state)
    assert status(rendered)["drift"] == drift
    assert status(rendered)["extra"] == extra
    assert ready(rendered) == ("False" if drift or extra else "True")


def test_a_write_that_succeeded_records_what_it_put_back(render):
    xr = example("Merge")
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
    xr = example("Merge")
    req = request(render, xr)
    before = render(KIND, xr, [answered(req, "profile-no-ikev2-profile")], DEVICES)
    xr["status"] = status(before)
    rendered = render(
        KIND, xr, [answered(req, "profile-no-ikev2-profile", "PATCH", 409)], DEVICES
    )
    assert status(rendered) == xr["status"]
    assert ready(rendered) == "False"
