"""Ikev2Policy: the check its Request observes with, on the router's recorded answers."""

import json

import pytest
from conftest import check, recorded

KIND = "ikev2policy"
XR = "r1-ikev2-policy"


@pytest.mark.parametrize(
    ("state", "up_to_date"),
    [
        ("policy-applied", True),
        # One field away from the example each.
        ("policy-extra-proposal", False),
        ("policy-other-proposal", False),
        ("policy-with-match", False),
        ("policy-absent", False),
    ],
)
def test_policy_compares_the_proposals_and_no_match(rendered, state, up_to_date):
    policy = rendered[XR]["policy"]
    result = check(policy, "expectedResponseCheck", recorded(KIND, state))
    assert result is up_to_date


def test_policy_puts_what_the_router_then_returns(rendered):
    body = rendered[XR]["policy"]["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "policy-applied")["body"]
