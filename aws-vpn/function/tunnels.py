"""Each tunnel as the cluster has it: AWS's number of it, its addresses, and whether it is up.

The position in spec.tunnels is AWS's number of the tunnel, 1 or 2: the VPN connection takes
tunnel 1's fields from the first, tunnel 2's from the second.
"""

import json


def read(xr: dict, composed: dict) -> list[dict]:
    customer_gateway = xr["spec"]["customerGateway"]
    vpn = composed.get("vpn-connection", {}).get("status", {}).get("atProvider", {})
    neighbours = bgp_neighbours(composed.get("bgp", {}))
    # how the router's BGP data names a neighbour of the tunnels' table
    if customer_gateway.get("insideVrf"):
        table = f"vpnv4-unicast,{customer_gateway['insideVrf']}"
    else:
        table = "ipv4-unicast,default"

    tunnels = []
    for aws_tunnel, spec in enumerate(xr["spec"]["tunnels"], start=1):
        tunnel_interface = composed.get(f"tunnel-{aws_tunnel}", {})
        oper = tunnel_interface.get("status", {}).get("oper", {})
        given = tunnel_interface.get("spec", {})

        # AWS's addresses once the VPN connection has them; while they are missing, the ones
        # the tunnel interface was given, so the router's side stays as it is
        inside_cidr = vpn.get(f"tunnel{aws_tunnel}InsideCidr") or spec["insideCidr"]
        router_inside = vpn.get(f"tunnel{aws_tunnel}CgwInsideAddress")
        if router_inside:
            inside = f"{router_inside}/{inside_cidr.split('/')[1]}"
        else:
            inside = given.get("ipv4Address", "")
        outside = vpn.get(f"tunnel{aws_tunnel}Address") or given.get("destination", "")

        # AWS's inside address is the router's BGP neighbour; none: the router has no such
        # neighbour, so nothing waits on a session that is never configured
        aws_inside = vpn.get(f"tunnel{aws_tunnel}VgwInsideAddress", "")
        bgp = None
        if neighbours is not None and aws_inside:
            bgp = neighbours.get(f"{table},{aws_inside}", "none")

        interface_ready = oper.get("interface") == "ready"
        ike_sa_active = oper.get("activePeers") == "1/1"
        bgp_ok = bgp in ("established", "none")

        tunnels.append(
            {
                "awsTunnel": aws_tunnel,
                "interface": spec["interface"],
                "insideCidr": spec["insideCidr"],
                "outside": outside,
                "inside": inside,
                "oper": oper.get("interface"),
                "bgp": bgp,
                "up": interface_ready and ike_sa_active and bgp_ok,
            }
        )
    return tunnels


def bgp_neighbours(read: dict) -> dict | None:
    """Each neighbour's session state by `<afi-safi>,<vrf>,<address>`, as the last read of the
    router found them; None before a read has answered. A 204 is a router without BGP."""
    answer = read.get("status", {}).get("response", {})
    code = int(answer.get("statusCode") or 0)
    if code == 204:
        return {}
    if code != 200:
        return None
    body = json.loads(answer.get("body") or "{}")
    found = body.get("Cisco-IOS-XE-bgp-oper:neighbors", {}).get("neighbor", [])
    states = {}
    for n in found:
        key = f"{n['afi-safi']},{n['vrf-name']},{n['neighbor-id']}"
        states[key] = n["session-state"].removeprefix("fsm-")
    return states
