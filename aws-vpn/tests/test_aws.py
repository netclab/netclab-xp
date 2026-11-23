"""The AWS side of a Connection: the customer gateway and the VPN connection it composes,
and status.aws from what the provider reports."""

from conftest import device, example, secret, status, vpn_connection


def test_the_vpn_connection_reads_the_applied_keys(render):
    vpn = render(example()).resources["vpn-connection"]["spec"]["forProvider"]
    assert vpn["tunnel1PresharedKeySecretRef"] == {
        "name": "edge1-aws-applied-keys",
        "key": "tunnel1",
    }
    assert vpn["tunnel2PresharedKeySecretRef"] == {
        "name": "edge1-aws-applied-keys",
        "key": "tunnel2",
    }
    assert [vpn["tunnel1InsideCidr"], vpn["tunnel2InsideCidr"]] == [
        "169.254.10.0/30",
        "169.254.10.4/30",
    ]


def test_new_keys_give_the_vpn_connection_a_new_mark(render):
    def mark(**keys):
        # no tunnel is up, so the applied keys are the user's at once
        rendered = render(example(), [], [device(), secret(**keys)])
        return rendered.resources["vpn-connection"]["metadata"]["annotations"][
            "aws-vpn.netclab.dev/keys"
        ]

    assert mark() == mark()
    assert mark() != mark(tunnel1="Other")


def test_an_asn_beyond_2147483647_goes_to_bgp_asn_extended(render):
    def gateway(asn):
        xr = example(bgpAsn=asn)
        return render(xr).resources["customer-gateway"]["spec"]["forProvider"]

    assert gateway(65010)["bgpAsn"] == "65010"
    assert "bgpAsnExtended" not in gateway(65010)
    assert gateway(4200000000)["bgpAsnExtended"] == "4200000000"
    assert "bgpAsn" not in gateway(4200000000)


def test_the_target_is_a_vpn_or_a_transit_gateway(render):
    xr = example()
    vpn = render(xr).resources["vpn-connection"]["spec"]["forProvider"]
    assert vpn["vpnGatewayId"] == "vgw-0123456789abcdef0"
    assert "transitGatewayId" not in vpn
    del xr["spec"]["targetGateway"]["vpnGatewayId"]
    xr["spec"]["targetGateway"]["transitGatewayId"] = "tgw-0123456789abcdef0"
    vpn = render(xr).resources["vpn-connection"]["spec"]["forProvider"]
    assert vpn["transitGatewayId"] == "tgw-0123456789abcdef0"
    assert "vpnGatewayId" not in vpn


def test_status_aws_matches_telemetry_by_outside_address(render):
    at = {
        "id": "vpn-0123456789abcdef0",
        "tunnel1Address": "203.0.113.1",
        "tunnel2Address": "203.0.113.2",
        "tunnel1VgwInsideAddress": "169.254.10.1",
        "tunnel2VgwInsideAddress": "169.254.10.5",
        # AWS's list in its own order, not tunnel 1 then tunnel 2
        "vgwTelemetry": [
            {"outsideIpAddress": "203.0.113.2", "status": "DOWN", "statusMessage": ""},
            {
                "outsideIpAddress": "203.0.113.1",
                "status": "UP",
                "statusMessage": "2 BGP ROUTES",
            },
        ],
    }
    aws = status(render(example(), [vpn_connection(at)]))["aws"]
    assert aws["vpnConnectionId"] == "vpn-0123456789abcdef0"
    assert [(t["outsideAddress"], t["oper"], t["message"]) for t in aws["tunnels"]] == [
        ("203.0.113.1", "UP", "2 BGP ROUTES"),
        ("203.0.113.2", "DOWN", ""),
    ]
    assert [t["insideAddress"] for t in aws["tunnels"]] == [
        "169.254.10.1",
        "169.254.10.5",
    ]


def test_no_status_aws_before_the_provider_reports(render):
    assert "aws" not in status(render(example()))
