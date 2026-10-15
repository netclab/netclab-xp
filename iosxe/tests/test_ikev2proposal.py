"""Ikev2Proposal: the check its Request observes with, on the router's recorded answers."""

import json

import pytest
from conftest import check, recorded

KIND = "ikev2proposal"
XR = "r1-ikev2-proposal"


@pytest.mark.parametrize(
    ("state", "up_to_date"),
    [
        ("proposal-applied", True),
        # One field away from the example each.
        ("proposal-extra-encryption", False),
        ("proposal-other-integrity", False),
        ("proposal-with-prf", False),
        ("proposal-other-group", False),
        ("proposal-absent", False),
    ],
)
def test_proposal_compares_the_algorithm_sets(rendered, state, up_to_date):
    proposal = rendered[XR]["proposal"]
    result = check(proposal, "expectedResponseCheck", recorded(KIND, state))
    assert result is up_to_date


def test_proposal_puts_what_the_router_then_returns(rendered):
    body = rendered[XR]["proposal"]["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "proposal-applied")["body"]
