"""Ikev2Profile: the checks its Requests observe with, on the router's recorded answers,
and the RPC composed after the profile."""

import json

import pytest
from conftest import IOSXE, check, in_namespace, observed, recorded

KIND = "ikev2profile"
XR = "r1-ikev2-profile"


@pytest.mark.parametrize(
    ("state", "up_to_date"),
    [
        ("profile-applied", True),
        # The PPK mark and a missing mask are not the profile's business.
        ("profile-marked", True),
        ("profile-no-mask", True),
        # One field away from the example each.
        ("profile-other-address", False),
        ("profile-extra-address", False),
        ("profile-absent", False),
    ],
)
def test_profile_compares_all_but_the_mark(rendered, state, up_to_date):
    profile = rendered[XR]["profile"]
    result = check(profile, "expectedResponseCheck", recorded(KIND, state))
    assert result is up_to_date


def test_profile_puts_what_the_router_then_returns(rendered):
    body = rendered[XR]["profile"]["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "profile-applied")["body"]


@pytest.mark.parametrize(
    ("state", "removed"),
    [
        ("profile-marked", False),
        ("profile-old-mark", True),
        ("profile-applied", True),
        ("profile-absent", True),
    ],
)
def test_ppk_is_present_only_with_its_mark(rendered, state, removed):
    ppk = rendered[XR]["ppk"]
    assert check(ppk, "isRemovedCheck", recorded(KIND, state)) is removed


def test_ppk_clears_the_peers_sas_with_the_line(rendered):
    body = json.loads(rendered[XR]["ppk"]["spec"]["forProvider"]["payload"]["body"])
    clis = body["Cisco-IOS-XE-cli-rpc:input"]["config-clis"].splitlines()
    assert clis == [
        "crypto ikev2 profile CLASSICAL-PROFILE",
        " keyring ppk CLASSICAL-KEYRING",
        " description ppk CLASSICAL-KEYRING",
        "do clear crypto ikev2 sa remote 10.0.23.2",
    ]


@pytest.mark.parametrize(
    ("before", "composed"),
    [
        # Nothing composed yet, or the profile not Ready: the profile alone.
        ({}, ["profile"]),
        ({"profile": False}, ["profile"]),
        # The profile Ready: the RPC with it.
        ({"profile": True}, ["profile", "ppk"]),
        # An RPC composed before stays, whatever the profile does.
        ({"profile": False, "ppk": False}, ["profile", "ppk"]),
    ],
)
def test_rpc_waits_for_the_profile(rendered, render, before, composed):
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    seen = [observed(rendered[XR][name], ready) for name, ready in before.items()]
    resources = render(KIND, xr, seen).resources
    # The Usage of the keyring the example waits on comes with them.
    requests = [r for r in resources if not r.startswith("after-")]
    assert sorted(requests) == sorted(composed)
