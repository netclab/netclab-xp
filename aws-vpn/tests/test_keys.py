"""The tunnels' keys: the Connection's Secret of applied keys, which follows the user's
Secret one tunnel at a time while the other tunnel is up, or at once when none is."""

import pytest
from conftest import (
    applied,
    bgp,
    device,
    example,
    neighbour,
    secret,
    status,
    tunnel,
    values,
    vpn_connection,
)


def rotation(aws_tunnel, step, since="2026-11-23T15:00:00Z"):
    return {
        "awsTunnel": aws_tunnel,
        "interface": f"Tunnel{aws_tunnel}",
        "step": step,
        "since": since,
    }


def sessions(tunnel1="established", tunnel2="established"):
    """The router's read of its BGP neighbours, each session to AWS's inside address of a
    tunnel in this state; none: the router has no such neighbour."""
    found = [
        neighbour("ipv4-unicast", "default", address, f"fsm-{state}")
        for address, state in (("169.254.10.1", tunnel1), ("169.254.10.5", tunnel2))
        if state != "none"
    ]
    return bgp(200, found)


def keys(render, user, observed, old=None, read=None):
    """The applied keys and status after one render: the user's Secret `user`, the old
    status `old`, the BGP read `read` (both sessions established unless given)."""
    xr = example(status=old)
    read = sessions() if read is None else read
    rendered = render(xr, [vpn_connection(), read, *observed], [device(), user])
    return values(rendered), status(rendered)


def test_a_new_connection_applies_the_users_keys(render):
    got, st = keys(render, secret("A1", "A2"), [])
    assert got == {"tunnel1": "A1", "tunnel2": "A2"}
    assert "rotation" not in st
    assert [k["wanted"] == k["applied"] for k in st["keys"]] == [True, True]


def test_marks_never_values(render):
    _, st = keys(render, secret("A1", "A2"), [])
    marks = [m for k in st["keys"] for m in (k["wanted"], k["applied"])]
    assert all(len(m) == 8 and m not in ("A1", "A2") for m in marks)


def test_both_keys_new_and_both_up_starts_with_tunnel_1(render):
    got, st = keys(
        render, secret("N1", "N2"), [applied("A1", "A2"), tunnel(1), tunnel(2)]
    )
    assert got == {"tunnel1": "N1", "tunnel2": "A2"}
    assert {k: st["rotation"][k] for k in ("interface", "step")} == {
        "interface": "Tunnel1",
        "step": "sent",
    }
    assert [k["wanted"] == k["applied"] for k in st["keys"]] == [True, False]


def test_sent_then_down_while_aws_rebuilds(render):
    old = {"rotation": rotation(1, "sent")}
    got, st = keys(
        render,
        secret("N1", "N2"),
        [applied("N1", "A2"), tunnel(1, False), tunnel(2)],
        old,
    )
    assert got == {"tunnel1": "N1", "tunnel2": "A2"}
    assert st["rotation"] == rotation(1, "down")


def test_sent_and_still_up_waits(render):
    old = {"rotation": rotation(1, "sent", "2099-01-01T00:00:00Z")}
    got, st = keys(
        render, secret("N1", "N2"), [applied("N1", "A2"), tunnel(1), tunnel(2)], old
    )
    assert got == {"tunnel1": "N1", "tunnel2": "A2"}
    assert st["rotation"]["step"] == "sent"


def test_up_again_moves_on_to_tunnel_2(render):
    old = {"rotation": rotation(1, "down")}
    got, st = keys(
        render, secret("N1", "N2"), [applied("N1", "A2"), tunnel(1), tunnel(2)], old
    )
    assert got == {"tunnel1": "N1", "tunnel2": "N2"}
    assert st["rotation"]["interface"] == "Tunnel2"
    assert st["rotation"]["step"] == "sent"


def test_up_again_with_nothing_left_ends_the_rotation(render):
    old = {"rotation": rotation(2, "down")}
    got, st = keys(
        render, secret("N1", "N2"), [applied("N1", "N2"), tunnel(1), tunnel(2)], old
    )
    assert got == {"tunnel1": "N1", "tunnel2": "N2"}
    assert "rotation" not in st


def test_a_tunnel_never_seen_down_counts_as_done_after_20_minutes(render):
    old = {"rotation": rotation(1, "sent", "2026-11-23T10:00:00Z")}
    got, st = keys(
        render, secret("N1", "N2"), [applied("N1", "A2"), tunnel(1), tunnel(2)], old
    )
    assert got == {"tunnel1": "N1", "tunnel2": "N2"}
    assert st["rotation"]["interface"] == "Tunnel2"


def test_with_no_tunnel_up_every_key_goes_at_once(render):
    got, st = keys(
        render,
        secret("N1", "N2"),
        [applied("A1", "A2"), tunnel(1, False), tunnel(2, False)],
    )
    assert got == {"tunnel1": "N1", "tunnel2": "N2"}
    assert "rotation" not in st


@pytest.mark.parametrize(
    "state, moves",
    [("established", True), ("none", True), ("idle", False), ("active", False)],
)
def test_the_other_tunnel_counts_as_up_with_bgp_established_or_none(
    render, state, moves
):
    got, _ = keys(
        render,
        secret("N1", "A2"),
        [applied("A1", "A2"), tunnel(1), tunnel(2)],
        read=sessions("established", state),
    )
    assert got["tunnel1"] == ("N1" if moves else "A1")


def test_the_other_tunnel_down_holds_the_change(render):
    got, st = keys(
        render, secret("N1", "A2"), [applied("A1", "A2"), tunnel(1), tunnel(2, False)]
    )
    assert got == {"tunnel1": "A1", "tunnel2": "A2"}
    assert "rotation" not in st


def test_a_missing_key_keeps_the_applied_one(render):
    got, st = keys(
        render, secret("A1", None), [applied("A1", "A2"), tunnel(1), tunnel(2)]
    )
    assert got == {"tunnel1": "A1", "tunnel2": "A2"}
    assert st["missingSecrets"] == ["edge1-aws-keys/tunnel2"]
    assert "wanted" not in st["keys"][1]


def test_a_missing_secret_on_a_new_connection_composes_no_keys(render):
    rendered = render(example(), [], [device()])
    assert "keys" not in rendered.resources
    assert status(rendered)["missingSecrets"] == [
        "edge1-aws-keys/tunnel1",
        "edge1-aws-keys/tunnel2",
    ]
