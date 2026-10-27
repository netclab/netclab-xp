"""IpsecProfile: the check its Request observes with, on the router's recorded answers."""

import json

import pytest
from conftest import check, recorded

KIND = "ipsecprofile"
XR = "r1-ipsec-profile"


@pytest.mark.parametrize(
    ("state", "up_to_date"),
    [
        ("profile-applied", True),
        # One field away from the example each.
        ("profile-extra-transform-set", False),
        ("profile-other-transform-set", False),
        ("profile-no-ikev2-profile", False),
        ("profile-with-pfs", False),
        ("profile-absent", False),
    ],
)
def test_profile_compares_the_whole_profile(rendered, state, up_to_date):
    profile = rendered[XR]["profile"]
    result = check(profile, "expectedResponseCheck", recorded(KIND, state))
    assert result is up_to_date


def test_profile_puts_what_the_router_then_returns(rendered):
    body = rendered[XR]["profile"]["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "profile-applied")["body"]
