"""TunnelInterface: its name, its modes, the check its Request observes with on the router's
recorded answers, the status it makes of them, the mask its body carries for a prefix
length, and the state the router reports for it."""

import copy
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

KIND = "tunnelinterface"
XR = "r1--tunnel0--d311cfe5"
answered = partial(_answered, KIND)

# A prefix that ends in each octet, and both ends of the range.
MASKS = {
    0: "0.0.0.0",
    1: "128.0.0.0",
    8: "255.0.0.0",
    12: "255.240.0.0",
    17: "255.255.128.0",
    20: "255.255.240.0",
    31: "255.255.255.254",
    32: "255.255.255.255",
}


def example(policy=None, **spec):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    # No `after`: the requests are composed at once.
    del xr["spec"]["after"]
    if policy:
        xr["spec"]["managementPolicy"] = policy
    else:
        del xr["spec"]["managementPolicy"]
    xr["spec"].update(spec)
    return xr


def thin(name="Tunnel0", xr_name=XR):
    """An object as Step 3 imports it: deviceRef and name, no mode."""
    return {
        "apiVersion": "iosxe.netclab.dev/v1alpha1",
        "kind": "TunnelInterface",
        "metadata": {"name": xr_name, "namespace": "lab"},
        "spec": {"deviceRef": {"name": "r1"}, "name": name},
    }


def request(render, xr):
    return render(KIND, xr, required=DEVICES).resources["tunnel"]


def test_an_object_under_another_name_composes_nothing(render):
    xr = thin(xr_name="r1-tunnel0")
    rendered = render(KIND, xr, required=DEVICES)
    assert rendered.resources == {}
    assert rendered.composite["status"]["wantsName"] == XR
    assert ready(rendered) == "False"
    xr["metadata"]["name"] = XR
    assert requests(render(KIND, xr, required=DEVICES).resources) == ["tunnel"]


def test_the_name_gives_the_interface_number(render):
    xr = thin("Tunnel12", "r1--tunnel12--" + "x" * 8)
    wants = render(KIND, xr, required=DEVICES).composite["status"]["wantsName"]
    xr["metadata"]["name"] = wants
    url = request(render, xr)["spec"]["forProvider"]["payload"]["baseUrl"]
    assert url.endswith("/interface/Tunnel=12")


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


def test_manage_sends_the_patch_the_router_merged(render):
    for_provider = request(render, example("Merge"))["spec"]["forProvider"]
    sent = recorded(KIND, "tunnel-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


def test_replace_puts_what_the_router_then_returns(render):
    body = request(render, example("Replace"))["spec"]["forProvider"]
    assert (
        json.loads(body["payload"]["body"]) == recorded(KIND, "tunnel-applied")["body"]
    )


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("tunnel-applied", True, True),
        # A line the spec cannot hold: Merge leaves it, Replace takes it off.
        ("tunnel-shutdown", True, False),
        # Merge's PATCH over a description made by hand, merged by the router.
        ("tunnel-patched", True, False),
        # A value of the spec the router lacks.
        ("tunnel-host-mask", False, False),
        ("tunnel-other-destination", False, False),
        ("tunnel-gre", False, False),
        ("tunnel-no-protection", False, False),
        ("tunnel-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
        req = request(render, example(policy))
        assert check(req, "expectedResponseCheck", recorded(KIND, state)) is expected


@pytest.fixture(scope="module")
def after_get(render):
    """The XR rendered with its Request answered by a GET of the router in `state`."""

    def _after_get(xr, state):
        return render(KIND, xr, [answered(request(render, xr), state)], DEVICES)

    return _after_get


APPLIED = {
    "mode": "ipsec-ipv4",
    "ipv4Address": "192.168.100.1/24",
    "source": "GigabitEthernet2",
    "destination": "10.0.23.2",
    "ipsecProfile": "CLASSICAL-IPSEC",
}


@pytest.mark.parametrize(
    ("state", "differs"),
    [
        ("tunnel-applied", {}),
        # The mask back as a prefix length.
        ("tunnel-host-mask", {"ipv4Address": "192.168.100.1/32"}),
        # A mode the spec cannot hold, as JSON.
        ("tunnel-gre", {"mode": '{"gre-config":{"ip":true}}'}),
        ("tunnel-no-protection", {"ipsecProfile": None}),
    ],
)
def test_a_thin_object_shows_the_router_in_the_shape_of_the_spec(
    after_get, state, differs
):
    rendered = after_get(thin(), state)
    seen = {k: v for k, v in {**APPLIED, **differs}.items() if v is not None}
    assert status(rendered) == {"observed": seen, "drift": [], "extra": []}
    assert ready(rendered) == "True"


def test_a_section_gone_from_the_router_is_not_ready(after_get):
    xr = thin()
    xr["status"] = {"observed": {"mode": "ipsec-ipv4"}, "drift": [], "extra": []}
    rendered = after_get(xr, "tunnel-absent")
    assert "observed" not in status(rendered)
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "state", "drift", "extra", "is_ready"),
    [
        (
            None,
            "tunnel-other-destination",
            [{"field": "destination", "device": ["10.0.23.9"], "spec": ["10.0.23.2"]}],
            [],
            "False",
        ),
        (
            "Merge",
            "tunnel-no-protection",
            [{"field": "ipsecProfile", "device": [], "spec": ["CLASSICAL-IPSEC"]}],
            [],
            "False",
        ),
        # A line the spec cannot hold: compared in Replace alone.
        ("Merge", "tunnel-patched", [], [], "True"),
        (
            "Replace",
            "tunnel-patched",
            [],
            [{"field": "description", "device": ['"made by hand"']}],
            "False",
        ),
        (
            "Replace",
            "tunnel-shutdown",
            [],
            [{"field": "shutdown", "device": ["[null]"]}],
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
    req = request(render, xr)
    before = render(KIND, xr, [answered(req, "tunnel-other-destination")], DEVICES)
    xr["status"] = status(before)
    code = recorded(KIND, "tunnel-patch")["statusCode"]
    rendered = render(
        KIND, xr, [answered(req, "tunnel-other-destination", "PATCH", code)], DEVICES
    )
    assert status(rendered)["drift"] == []
    assert status(rendered)["reverted"]["drift"] == xr["status"]["drift"]
    assert ready(rendered) == "True"


def test_a_write_that_failed_changes_nothing(render):
    xr = example("Merge")
    req = request(render, xr)
    before = render(KIND, xr, [answered(req, "tunnel-other-destination")], DEVICES)
    xr["status"] = status(before)
    rendered = render(
        KIND, xr, [answered(req, "tunnel-other-destination", "PATCH", 409)], DEVICES
    )
    assert status(rendered) == xr["status"]
    assert ready(rendered) == "False"


@pytest.fixture(scope="module")
def masks(render):
    """The mask in the body for each prefix length of MASKS, one render each."""
    out = {}
    for length in MASKS:
        xr = example("Replace", ipv4Address=f"192.168.100.1/{length}")
        body = request(render, xr)["spec"]["forProvider"]["payload"]["body"]
        tunnel = json.loads(body)["Cisco-IOS-XE-native:Tunnel"][0]
        out[length] = tunnel["ip"]["address"]["primary"]["mask"]
    return out


@pytest.mark.parametrize(("length", "mask"), MASKS.items())
def test_tunnel_turns_the_prefix_length_into_a_mask(masks, length, mask):
    assert masks[length] == mask


def read(request, response):
    """A read-only Request as provider-http leaves it after an answer: the body a string."""
    out = observed(request, True)
    body = response["body"]
    out["status"]["response"] = {
        "statusCode": response["statusCode"],
        "body": body if isinstance(body, str) else json.dumps(body),
    }
    return out


def sa_elsewhere():
    """An active SA, to another address than the tunnel's destination."""
    out = copy.deepcopy(recorded(KIND, "sa-active"))
    for sa in out["body"]["Cisco-IOS-XE-crypto-oper:crypto-ikev2-sa"]:
        sa["sa-data"]["remote-ip-addr"] = "10.0.23.9"
    return out


@pytest.fixture(scope="module")
def state(rendered, render):
    """state(oper, sa, xr): the XR's status.oper with these answers to its two reads."""
    resources = rendered[XR]

    def _state(oper, sa, xr=None):
        xr = xr or in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
        before = [
            answered(resources["tunnel"], "tunnel-applied"),
            read(resources["oper"], recorded(KIND, oper)),
            read(
                resources["ike-sa"], sa if isinstance(sa, dict) else recorded(KIND, sa)
            ),
        ]
        return render(KIND, xr, before).composite["status"].get("oper")

    return _state


def peer(ike_sa):
    return [{"address": "10.0.23.2", "ikeSA": ike_sa}]


@pytest.mark.parametrize(
    ("oper", "sa", "expected"),
    [
        (
            "oper-ready",
            "sa-active",
            {"interface": "ready", "activePeers": "1/1", "peers": peer("active")},
        ),
        (
            "oper-lower-layer-down",
            "sa-pending",
            {
                "interface": "lower-layer-down",
                "activePeers": "0/1",
                "peers": peer("pending"),
            },
        ),
        # No tunnel: 404 for the interface, 204 for the SAs.
        ("oper-absent", "sa-none", {"activePeers": "0/1", "peers": peer("none")}),
    ],
)
def test_status_carries_what_the_router_reports(state, oper, sa, expected):
    assert state(oper, sa) == expected


def test_a_thin_object_counts_the_sa_to_the_router_s_destination(state):
    assert state("oper-ready", "sa-active", thin())["peers"] == peer("active")


def test_status_counts_only_the_sa_to_the_destination(state):
    assert state("oper-ready", sa_elsewhere())["peers"] == peer("none")


def test_status_takes_the_active_sa_of_several_to_the_destination(state):
    # The recorded answer lists a pending SA, then the active one; here the other way.
    sa = copy.deepcopy(recorded(KIND, "sa-active"))
    sa["body"]["Cisco-IOS-XE-crypto-oper:crypto-ikev2-sa"].reverse()
    assert state("oper-ready", sa)["peers"] == peer("active")


def test_reads_the_router_once_the_tunnel_request_exists(render, rendered):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    first = render(KIND, xr).resources
    assert sorted(first) == [
        "after-device-r1",
        "after-ipsecprofile-r1--classical-ipsec--461c477a",
        "tunnel",
    ]
    for name in ("oper", "ike-sa"):
        assert rendered[XR][name]["spec"]["managementPolicies"] == ["Observe"]


def test_state_never_holds_back_ready(render, rendered):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    # The tunnel as on the router and the Usage Ready, the two reads not.
    before = [
        answered(r, "tunnel-applied")
        if name == "tunnel"
        else observed(r, name not in ("oper", "ike-sa"))
        for name, r in rendered[XR].items()
    ]
    assert ready(render(KIND, xr, before)) == "True"
