"""The tunnels' keys: the Connection's Secret of applied keys, which follows the user's
Secret one tunnel at a time while the other tunnel is up, or at once when none is."""

import pytest
from conftest import (
    applied,
    device,
    example,
    secret,
    status,
    tunnel,
    values,
    vpn_connection,
)

ESTABLISHED = {"router": {"tunnels": [{"bgp": "established"}, {"bgp": "established"}]}}


def rotation(interface, step, since="2026-11-23T15:00:00Z"):
    return {"interface": interface, "step": step, "since": since}


def keys(render, user, observed, old=None):
    """The applied keys and status after one render: the user's Secret `user`, the old
    status `old` (both tunnels established unless given)."""
    xr = example(status=ESTABLISHED if old is None else old)
    rendered = render(xr, [vpn_connection(), *observed], [device(), user])
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
    old = dict(ESTABLISHED, rotation=rotation("Tunnel1", "sent"))
    got, st = keys(
        render,
        secret("N1", "N2"),
        [applied("N1", "A2"), tunnel(1, False), tunnel(2)],
        old,
    )
    assert got == {"tunnel1": "N1", "tunnel2": "A2"}
    assert st["rotation"] == rotation("Tunnel1", "down")


def test_sent_and_still_up_waits(render):
    old = dict(
        ESTABLISHED, rotation=rotation("Tunnel1", "sent", "2099-01-01T00:00:00Z")
    )
    got, st = keys(
        render, secret("N1", "N2"), [applied("N1", "A2"), tunnel(1), tunnel(2)], old
    )
    assert got == {"tunnel1": "N1", "tunnel2": "A2"}
    assert st["rotation"]["step"] == "sent"


def test_up_again_moves_on_to_tunnel_2(render):
    old = dict(ESTABLISHED, rotation=rotation("Tunnel1", "down"))
    got, st = keys(
        render, secret("N1", "N2"), [applied("N1", "A2"), tunnel(1), tunnel(2)], old
    )
    assert got == {"tunnel1": "N1", "tunnel2": "N2"}
    assert st["rotation"]["interface"] == "Tunnel2"
    assert st["rotation"]["step"] == "sent"


def test_up_again_with_nothing_left_ends_the_rotation(render):
    old = dict(ESTABLISHED, rotation=rotation("Tunnel2", "down"))
    got, st = keys(
        render, secret("N1", "N2"), [applied("N1", "N2"), tunnel(1), tunnel(2)], old
    )
    assert got == {"tunnel1": "N1", "tunnel2": "N2"}
    assert "rotation" not in st


def test_a_tunnel_never_seen_down_counts_as_done_after_20_minutes(render):
    old = dict(
        ESTABLISHED, rotation=rotation("Tunnel1", "sent", "2026-11-23T10:00:00Z")
    )
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
    "bgp, moves",
    [("established", True), ("none", True), ("idle", False), ("active", False)],
)
def test_the_other_tunnel_counts_as_up_with_bgp_established_or_none(render, bgp, moves):
    old = {"router": {"tunnels": [{"bgp": "established"}, {"bgp": bgp}]}}
    got, _ = keys(
        render, secret("N1", "A2"), [applied("A1", "A2"), tunnel(1), tunnel(2)], old
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
