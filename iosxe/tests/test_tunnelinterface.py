"""TunnelInterface: the check its Request observes with, on the router's recorded answers,
the mask its body carries for a prefix length, and the state the router reports for it."""

import copy
import json

import pytest
from conftest import IOSXE, check, in_namespace, observed, recorded

KIND = "tunnelinterface"
XR = "r1-tunnel0"

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


@pytest.mark.parametrize(
    ("state", "up_to_date"),
    [
        ("tunnel-applied", True),
        # One field away from the example each.
        ("tunnel-host-mask", False),
        ("tunnel-other-destination", False),
        ("tunnel-gre", False),
        ("tunnel-no-protection", False),
        ("tunnel-shutdown", False),
        ("tunnel-absent", False),
    ],
)
def test_tunnel_compares_the_whole_interface(rendered, state, up_to_date):
    tunnel = rendered[XR]["tunnel"]
    result = check(tunnel, "expectedResponseCheck", recorded(KIND, state))
    assert result is up_to_date


def test_tunnel_puts_what_the_router_then_returns(rendered):
    body = rendered[XR]["tunnel"]["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "tunnel-applied")["body"]


@pytest.fixture(scope="module")
def masks(render):
    """The mask in the body for each prefix length of MASKS, one render each."""
    out = {}
    for length in MASKS:
        xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
        xr["metadata"]["name"] = f"{XR}-{length}"
        xr["spec"]["ipv4Address"] = f"192.168.100.1/{length}"
        tunnel = render(KIND, xr).resources["tunnel"]["spec"]["forProvider"]
        body = json.loads(tunnel["payload"]["body"])["Cisco-IOS-XE-native:Tunnel"][0]
        out[length] = body["ip"]["address"]["primary"]["mask"]
    return out


@pytest.mark.parametrize(("length", "mask"), MASKS.items())
def test_tunnel_turns_the_prefix_length_into_a_mask(masks, length, mask):
    assert masks[length] == mask


def answered(request, response):
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
    """state(oper, sa): the XR's status.oper with these answers to its two reads."""
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    resources = rendered[XR]

    def _state(oper, sa):
        before = [
            observed(resources["tunnel"], True),
            answered(resources["oper"], recorded(KIND, oper)),
            answered(
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
    assert sorted(first) == ["after-ipsecprofile-r1-ipsec-profile", "tunnel"]
    for name in ("oper", "ike-sa"):
        assert rendered[XR][name]["spec"]["managementPolicies"] == ["Observe"]


def test_state_never_holds_back_ready(render, rendered):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    # The tunnel and the Usage Ready, the two reads not.
    before = [
        observed(r, name not in ("oper", "ike-sa")) for name, r in rendered[XR].items()
    ]
    conditions = render(KIND, xr, before).composite["status"]["conditions"]
    assert {c["type"]: c["status"] for c in conditions}["Ready"] == "True"
