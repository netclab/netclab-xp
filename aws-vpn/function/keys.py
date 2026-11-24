"""The tunnels' keys, rotated one tunnel at a time, as by hand:

  1. the new key goes to one tunnel while the other one carries traffic   (step: sent)
  2. AWS rebuilds that tunnel, so it goes down                             (step: down)
  3. once it is up again on the new key, the other tunnel takes its turn

With both tunnels down nothing carries traffic, so both keys go at once. A tunnel never seen
down counts as done after 20 minutes up.

Both ends read the keys from a Secret of the Connection's own, the applied Secret: the VPN
connection and the router's keyring. It holds each tunnel's key under tunnel<number>.
"""

import hashlib
from datetime import UTC, datetime

STAMP = "%Y-%m-%dT%H:%M:%SZ"
UP_WITHOUT_DOWN_MINUTES = 20


def rotate(
    xr: dict, tunnels: list[dict], user_secrets: dict, applied_secret: dict, now
):
    """The applied Secret's data, and status.keys, status.rotation and status.missingSecrets."""
    uid = xr["metadata"]["uid"]
    status = xr.get("status", {})  # written by the previous pass

    # Each tunnel: the key the user wants, the key both ends have.
    for tunnel, spec in zip(tunnels, xr["spec"]["tunnels"], strict=True):
        ref = spec["preSharedKeySecretRef"]
        user_secret = user_secrets.get(ref["name"], {})
        tunnel["ref"] = f"{ref['name']}/{ref['key']}"
        tunnel["userKey"] = user_secret.get("data", {}).get(ref["key"], "")
        tunnel["appliedKey"] = applied_secret.get("data", {}).get(
            secret_key(tunnel), ""
        )
    t1, t2 = tunnels
    # what both ends get in this pass: the key they have, the user's on a new connection
    desired_keys = {
        1: t1["appliedKey"] or t1["userKey"],
        2: t2["appliedKey"] or t2["userKey"],
    }

    # The rotation in progress.
    rotation = dict(status.get("rotation", {}))
    if rotation:
        t = t1 if rotation.get("awsTunnel") == 1 else t2
        since = datetime.strptime(rotation["since"], STAMP).replace(tzinfo=UTC)
        minutes = (now - since).total_seconds() / 60
        if rotation["step"] == "sent" and not t["up"]:
            rotation["step"] = "down"
        elif t["up"] and (
            rotation["step"] == "down" or minutes >= UP_WITHOUT_DOWN_MINUTES
        ):
            rotation = {}

    # A new rotation, once none is in progress.
    if not rotation:
        new = [
            t
            for t in tunnels
            if t["appliedKey"] and t["userKey"] and t["userKey"] != t["appliedKey"]
        ]
        if not t1["up"] and not t2["up"]:
            for t in new:
                desired_keys[t["awsTunnel"]] = t["userKey"]
        else:
            for t, other in ((t1, t2), (t2, t1)):
                if t in new and other["up"]:
                    desired_keys[t["awsTunnel"]] = t["userKey"]
                    rotation = {
                        "awsTunnel": t["awsTunnel"],
                        "interface": t["interface"],
                        "step": "sent",
                        "since": now.strftime(STAMP),
                    }
                    break

    # Out: the applied Secret's data, and marks of the keys, never the keys.
    data = {secret_key(t): desired_keys[t["awsTunnel"]] for t in tunnels}
    data = {key: value for key, value in data.items() if value}
    marks = []
    for t in tunnels:
        m = {"interface": t["interface"]}
        if t["userKey"]:
            m["wanted"] = mark(uid, t["userKey"])
        if desired_keys[t["awsTunnel"]]:
            m["applied"] = mark(uid, desired_keys[t["awsTunnel"]])
        marks.append(m)
    out = {"keys": marks}
    if rotation:
        out["rotation"] = rotation
    missing = [t["ref"] for t in tunnels if not t["userKey"]]
    if missing:
        out["missingSecrets"] = missing
    return data, out


def secret_key(tunnel: dict) -> str:
    """The tunnel's key in the applied Secret."""
    return f"tunnel{tunnel['awsTunnel']}"


def mark(uid: str, key: str) -> str:
    return hashlib.sha256(f"{uid}/{key}".encode()).hexdigest()[:8]
