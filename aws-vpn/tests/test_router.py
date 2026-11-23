"""The router side of a Connection: what it composes once the VPN connection gives the
tunnels' addresses, under configuration-iosxe's names, and status.router."""

import json

import pytest
from conftest import composed, example, status, tunnel, vpn_connection

CHILDREN = [
    "ikev2-profile",
    "ipsec-profile",
    "keyring",
    "transform-set",
    "tunnel-1",
    "tunnel-2",
]
NAME = "edge1--edge1-aws--20c9e3b6"


def children(resources):
    return sorted(
        n for n, r in resources.items() if r["apiVersion"].startswith("iosxe.")
    )


@pytest.fixture(scope="module")
def up(render):
    """The example's children once the VPN connection has its addresses."""
    return render(example(), [vpn_connection()]).resources


def test_nothing_on_the_router_before_the_addresses(render):
    assert children(render(example()).resources) == []
    assert (
        children(render(example(), [vpn_connection({"id": "vpn-1"})]).resources) == []
    )


def test_the_children_once_the_addresses_are_there(up):
    assert children(up) == CHILDREN
    names = {n: up[n]["metadata"]["name"] for n in CHILDREN}
    assert names == {
        "keyring": NAME,
        "ikev2-profile": NAME,
        "transform-set": NAME,
        "ipsec-profile": NAME,
        "tunnel-1": "edge1--tunnel1--52d579fe",
        "tunnel-2": "edge1--tunnel2--3d049ed0",
    }
    assert {up[n]["spec"]["name"] for n in CHILDREN[:4]} == {"EDGE1-AWS"}
    assert {up[n]["spec"]["managementPolicy"] for n in CHILDREN} == {"Replace"}


def test_each_child_waits_on_what_it_names(up):
    after = {n: up[n]["spec"].get("after", []) for n in CHILDREN}
    assert after["keyring"] == [] and after["transform-set"] == []
    assert after["ikev2-profile"] == [{"kind": "Ikev2Keyring", "name": NAME}]
    assert after["ipsec-profile"] == [
        {"kind": "IpsecTransformSet", "name": NAME},
        {"kind": "Ikev2Profile", "name": NAME},
    ]
    assert (
        after["tunnel-1"]
        == after["tunnel-2"]
        == [{"kind": "IpsecProfile", "name": NAME}]
    )


def test_the_tunnels_take_their_addresses_from_aws(up):
    spec = {n: up[n]["spec"] for n in ("tunnel-1", "tunnel-2")}
    assert [(s["name"], s["ipv4Address"], s["destination"]) for s in spec.values()] == [
        ("Tunnel1", "169.254.10.2/30", "203.0.113.1"),
        ("Tunnel2", "169.254.10.6/30", "203.0.113.2"),
    ]
    assert up["keyring"]["spec"]["peers"] == [
        {
            "name": "TUNNEL1",
            "address": "203.0.113.1",
            "preSharedKeySecretRef": {
                "name": "edge1-aws-applied-keys",
                "key": "tunnel1",
            },
        },
        {
            "name": "TUNNEL2",
            "address": "203.0.113.2",
            "preSharedKeySecretRef": {
                "name": "edge1-aws-applied-keys",
                "key": "tunnel2",
            },
        },
    ]
    assert up["ikev2-profile"]["spec"]["remoteAddresses"] == [
        "203.0.113.1",
        "203.0.113.2",
    ]


def test_the_pass_throughs_go_under_what_the_connection_sets(up):
    assert up["ikev2-profile"]["spec"]["dpd"] == {
        "interval": 10,
        "retry": 10,
        "query": "on-demand",
    }
    assert up["ikev2-profile"]["spec"]["lifetime"] == 28800
    ipsec = up["ipsec-profile"]["spec"]
    assert (
        ipsec["pfs"],
        ipsec["lifetime"],
        ipsec["dfbit"],
        ipsec["replayWindowSize"],
    ) == (
        "group20",
        3600,
        "clear",
        128,
    )
    assert (
        ipsec["transformSets"] == ["EDGE1-AWS"] and ipsec["ikev2Profile"] == "EDGE1-AWS"
    )
    assert up["tunnel-1"]["spec"]["tcpAdjustMss"] == 1379
    assert (
        up["transform-set"]["spec"]["esp"],
        up["transform-set"]["spec"]["keyBits"],
    ) == (
        "esp-gcm",
        256,
    )


def test_without_pass_throughs_pfs_is_group14(render):
    xr = example(insideVrf="VPC")
    for k in (
        "ikev2ProfileSpec",
        "ipsecProfileSpec",
        "tunnelInterfaceSpec",
        "outsideVrf",
    ):
        del xr["spec"]["customerGateway"][k]
    r = render(xr, [vpn_connection()]).resources
    assert r["ipsec-profile"]["spec"]["pfs"] == "group14"
    assert (
        "fvrf" not in r["ikev2-profile"]["spec"] and "fvrf" not in r["tunnel-1"]["spec"]
    )
    assert r["tunnel-1"]["spec"]["vrf"] == "VPC"
    assert "tcpAdjustMss" not in r["tunnel-1"]["spec"]


def test_the_vrfs_reach_the_profile_and_the_tunnels(up):
    assert up["ikev2-profile"]["spec"]["fvrf"] == "WAN"
    assert up["tunnel-1"]["spec"]["fvrf"] == up["tunnel-2"]["spec"]["fvrf"] == "WAN"
    assert "vrf" not in up["tunnel-1"]["spec"]


def test_the_children_stay_when_the_addresses_go(render, up):
    before = [composed(n, up[n]["kind"], up[n]["apiVersion"]) for n in CHILDREN]
    for b, n in zip(before, CHILDREN):
        b["metadata"]["name"] = up[n]["metadata"]["name"]
        b["spec"] = up[n]["spec"]
    again = render(example(), [vpn_connection({"id": "vpn-1"}), *before]).resources
    assert children(again) == CHILDREN
    assert {n: again[n]["spec"] for n in CHILDREN} == {
        n: up[n]["spec"] for n in CHILDREN
    }


def bgp(code, neighbours=()):
    response = {"statusCode": code}
    if code == 200:
        response["body"] = json.dumps(
            {"Cisco-IOS-XE-bgp-oper:neighbors": {"neighbor": list(neighbours)}}
        )
    return composed(
        "bgp", "Request", "http.m.crossplane.io/v1alpha2", {"response": response}
    )


def neighbour(afi, vrf, address, state):
    return {
        "afi-safi": afi,
        "vrf-name": vrf,
        "neighbor-id": address,
        "session-state": state,
    }


def router(render, *observed, **customer_gateway):
    return status(
        render(
            example(**customer_gateway),
            [vpn_connection(), tunnel(1), tunnel(2), *observed],
        )
    )["router"]["tunnels"]


def test_one_bgp_read_once_a_tunnel_exists(render):
    assert "bgp" not in render(example(), [vpn_connection()]).resources
    read = render(example(), [vpn_connection(), tunnel(1)]).resources["bgp"]
    url = read["spec"]["forProvider"]["payload"]["baseUrl"]
    assert url == (
        "https://172.18.0.104/restconf/data/Cisco-IOS-XE-bgp-oper:bgp-state-data/neighbors"
        "?fields=neighbor(afi-safi;vrf-name;neighbor-id;session-state)"
    )


def test_status_router_before_the_read(render):
    assert router(render) == [
        {"interface": "Tunnel1", "address": "169.254.10.2/30", "oper": "ready"},
        {"interface": "Tunnel2", "address": "169.254.10.6/30", "oper": "ready"},
    ]


def test_bgp_by_aws_inside_address_none_where_no_neighbour(render):
    read = bgp(
        200,
        [
            neighbour("ipv4-unicast", "default", "169.254.10.1", "fsm-established"),
            neighbour("vpnv4-unicast", "VPC", "169.254.10.5", "fsm-idle"),
        ],
    )
    assert [t["bgp"] for t in router(render, read)] == ["established", "none"]
    assert [t["bgp"] for t in router(render, read, insideVrf="VPC")] == ["none", "idle"]


def test_a_router_without_bgp_answers_204(render):
    assert [t["bgp"] for t in router(render, bgp(204))] == ["none", "none"]
