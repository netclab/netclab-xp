"""Device: the Requests it reads the router with, and status.config, the router's blocks of
the package's kinds with the name each object must have and whether it is there."""

import copy
from functools import partial

import pytest
from conftest import EXAMPLES, in_namespace, observed, ready, secrets
from conftest import answered as _answered

KIND = "device"
answered = partial(_answered, KIND)
DEVICE = in_namespace(next(p for p in EXAMPLES if p.parent.name == "device"))
OBJECTS = [
    observed(in_namespace(p), True) for p in EXAMPLES if p.parent.name != "device"
]


def config(render, cfg, tunnels, required=None):
    """status.config of r1 with the reads answered as recorded in `cfg` and `tunnels`,
    the objects in the namespace `required`, by default the examples."""
    xr = copy.deepcopy(DEVICE)
    resources = render(KIND, xr, required=required or OBJECTS + secrets()).resources
    before = [
        observed(resources["hostname"], True),
        answered(resources["config"], cfg),
        answered(resources["tunnels"], tunnels),
    ]
    rendered = render(KIND, xr, before, required or OBJECTS + secrets())
    return rendered.composite["status"].get("config")


def entry(kind, name, xr, exists):
    return {"kind": kind, "name": name, "xr": xr, "exists": exists}


def test_lists_each_block_with_the_name_its_object_must_have(render):
    assert config(render, "config-part9", "tunnels-part9") == [
        entry(
            "Ikev2Proposal",
            "CLASSICAL-PROPOSAL",
            "r1--classical-proposal--3a16aab3",
            True,
        ),
        # No object for it in the namespace.
        entry(
            "Ikev2Proposal", "LEGACY_PROPOSAL", "r1--legacy-proposal--d8cc32e4", False
        ),
        entry(
            "Ikev2Policy", "CLASSICAL-POLICY", "r1--classical-policy--17d97755", True
        ),
        entry(
            "Ikev2Keyring",
            "CLASSICAL-KEYRING",
            "r1--classical-keyring--eb60cb7d",
            True,
        ),
        entry(
            "Ikev2Profile", "CLASSICAL-PROFILE", "r1--classical-profile--cdf1f733", True
        ),
        entry("IpsecTransformSet", "CLASSICAL-TS", "r1--classical-ts--771f3cb2", True),
        entry("IpsecProfile", "CLASSICAL-IPSEC", "r1--classical-ipsec--461c477a", True),
        entry("TunnelInterface", "Tunnel0", "r1--tunnel0--d311cfe5", True),
    ]


def test_an_object_for_another_device_is_not_this_block_s(render):
    others = copy.deepcopy(OBJECTS)
    for o in others:
        o["spec"]["deviceRef"]["name"] = "r3"
    listed = config(render, "config-part9", "tunnels-part9", others + secrets())
    assert not any(e["exists"] for e in listed)


def test_a_router_with_no_block_lists_none(render):
    assert config(render, "config-absent", "tunnels-absent") == []


def test_no_list_before_the_router_is_read(render):
    rendered = render(KIND, copy.deepcopy(DEVICE), required=OBJECTS + secrets())
    assert "config" not in rendered.composite.get("status", {})


@pytest.mark.parametrize("hostname", [True, False])
def test_the_hostname_alone_decides_ready(render, hostname):
    xr = copy.deepcopy(DEVICE)
    resources = render(KIND, xr, required=OBJECTS + secrets()).resources
    before = [
        observed(resources["hostname"], hostname),
        observed(resources["config"], False),
        observed(resources["tunnels"], False),
    ]
    rendered = render(KIND, xr, before, OBJECTS + secrets())
    assert ready(rendered) == ("True" if hostname else "False")
