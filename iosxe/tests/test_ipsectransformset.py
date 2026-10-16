"""IpsecTransformSet: the check its Request observes with, on the router's recorded answers."""

import json

import pytest
from conftest import check, recorded

KIND = "ipsectransformset"
XR = "r1-ipsec-transform-set"


@pytest.mark.parametrize(
    ("state", "up_to_date"),
    [
        ("transform-set-applied", True),
        # One field away from the example each.
        ("transform-set-key-bit-128", False),
        ("transform-set-transport", False),
        ("transform-set-aes-with-hmac", False),
        ("transform-set-absent", False),
    ],
)
def test_transform_set_compares_the_whole_transform(rendered, state, up_to_date):
    transform_set = rendered[XR]["transform-set"]
    result = check(transform_set, "expectedResponseCheck", recorded(KIND, state))
    assert result is up_to_date


def test_transform_set_puts_what_the_router_then_returns(rendered):
    body = rendered[XR]["transform-set"]["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(body) == recorded(KIND, "transform-set-applied")["body"]
