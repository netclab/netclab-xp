"""TunnelInterface: the check its Request observes with, on the router's recorded answers,
and the mask its body carries for a prefix length."""

import json

import pytest
from conftest import IOSXE, check, in_namespace, recorded

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
