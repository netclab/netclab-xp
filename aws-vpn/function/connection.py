"""The decisions of one Connection, for the composition's templates and for its status.

The templates compose what lands on AWS and on the router from the context written here;
this module decides, and composes only the applied Secret of keys.
"""

import hashlib
import json

from . import keys, names, tunnels

CONTEXT = "aws-vpn.netclab.dev/connection"


def decide(xr: dict, composed: dict, user_secrets: dict, device: dict, now):
    """The applied Secret's data, the Connection's status, and the context."""
    customer_gateway = xr["spec"]["customerGateway"]
    each = tunnels.read(xr, composed)
    applied_keys, status = keys.rotate(
        xr, each, user_secrets, composed.get("keys", {}), now
    )

    # The router: one name for its sections, configuration-iosxe's names of its objects.
    device_name = customer_gateway["deviceRef"]["name"]
    section = xr["metadata"]["name"].upper()
    xr_names = {section: names.xr_name(device_name, section)}
    for t in each:
        xr_names[t["interface"]] = names.xr_name(device_name, t["interface"])
    # the router's side once every tunnel has its addresses at both ends
    compose_router = all(t["outside"] and t["inside"] for t in each)
    # one read of the router's BGP neighbours, once a tunnel interface exists
    tunnel_interfaces = any(f"tunnel-{t['awsTunnel']}" in composed for t in each)

    router = {"name": section, "xrNames": xr_names, "compose": compose_router}
    if device and tunnel_interfaces:
        router["bgpRead"] = bgp_read(device)

    context = {
        "tunnels": [
            {
                "awsTunnel": t["awsTunnel"],
                "interface": t["interface"],
                "insideCidr": t["insideCidr"],
                "outside": t["outside"],
                "inside": t["inside"],
                "secretKey": keys.secret_key(t),
            }
            for t in each
        ],
        "keys": {
            "secret": f"{xr['metadata']['name']}-applied-keys",
            # a new mark makes the provider take new keys at once, not at its poll
            "mark": keys_mark(xr["metadata"]["uid"], applied_keys),
        },
        "router": router,
    }

    status["router"] = {"tunnels": [router_row(t) for t in each]}
    vpn = composed.get("vpn-connection", {}).get("status", {}).get("atProvider", {})
    if vpn:
        status["aws"] = aws_status(vpn)
    return applied_keys, status, context


def bgp_read(device: dict) -> dict:
    """Where the read of the BGP neighbours goes, and how it authenticates: provider-http
    puts the credentials from the Device's Secret in place of the {{ }}."""
    credentials = device["spec"]["credentialsSecretRef"]
    namespace = device["metadata"]["namespace"]
    return {
        "address": device["spec"]["address"],
        "insecureSkipTLSVerify": device["spec"].get("insecureSkipTLSVerify", False),
        "authorization": (
            f"Basic {{{{ {credentials['name']}:{namespace}:{credentials['key']} }}}}"
        ),
    }


def keys_mark(uid: str, applied_keys: dict) -> str:
    keys_json = json.dumps(applied_keys, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{uid}/{keys_json}".encode()).hexdigest()[:8]


def router_row(tunnel: dict) -> dict:
    row = {"interface": tunnel["interface"]}
    if tunnel["inside"]:
        row["address"] = tunnel["inside"]
    if tunnel["oper"]:
        row["oper"] = tunnel["oper"]
    if tunnel["bgp"] is not None:
        row["bgp"] = tunnel["bgp"]
    return row


def aws_status(vpn: dict) -> dict:
    """AWS's ends of each tunnel and its telemetry, matched by outside address, since AWS's
    list need not follow tunnel 1 and tunnel 2."""
    telemetry = {
        t.get("outsideIpAddress", ""): t for t in vpn.get("vgwTelemetry") or []
    }
    out = {}
    if vpn.get("customerGatewayId"):
        out["customerGatewayId"] = vpn["customerGatewayId"]
    if vpn.get("id"):
        out["vpnConnectionId"] = vpn["id"]
    out["tunnels"] = []
    for n in (1, 2):
        outside = vpn.get(f"tunnel{n}Address", "")
        row = {
            "outsideAddress": outside,
            "insideAddress": vpn.get(f"tunnel{n}VgwInsideAddress", ""),
            "bgpAsn": str(vpn.get(f"tunnel{n}BgpAsn") or ""),
        }
        if outside in telemetry:
            t = telemetry[outside]
            row["oper"] = t.get("status", "")
            row["lastChange"] = t.get("lastStatusChange", "")
            row["message"] = t.get("statusMessage", "")
        out["tunnels"].append(row)
    return out
