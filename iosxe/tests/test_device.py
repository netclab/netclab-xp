"""Device: the Requests it reads the router with, and status.config, the router's sections of
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


def reads(resources, hostname, cfg, tunnels):
    """The Device's Requests as observed: the hostname's Ready or not, and each read
    answered as recorded in its state, (state, status code) for another code, or not yet
    answered when None."""

    def read(name, state):
        if state is None:
            return observed(resources[name], True)
        state, status = state if isinstance(state, tuple) else (state, None)
        return answered(resources[name], state, status=status)

    return [
        observed(resources["hostname"], hostname),
        read("config", cfg),
        read("tunnels", tunnels),
    ]


def device(render, hostname, cfg, tunnels, required=None):
    """r1 rendered with its reads as `reads` gives them, the objects in the namespace
    `required`, by default the examples."""
    xr = copy.deepcopy(DEVICE)
    required = required or OBJECTS + secrets()
    resources = render(KIND, xr, required=required).resources
    return render(KIND, xr, reads(resources, hostname, cfg, tunnels), required)


def config(render, cfg, tunnels, required=None):
    """status.config of r1 with the reads answered as `reads` takes them."""
    rendered = device(render, True, cfg, tunnels, required)
    return rendered.composite["status"].get("config")


def entry(kind, name, xr, exists):
    return {"kind": kind, "name": name, "xr": xr, "exists": exists}


def test_lists_each_section_with_the_name_its_object_must_have(render):
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


def test_an_object_for_another_device_is_not_this_section_s(render):
    others = copy.deepcopy(OBJECTS)
    for o in others:
        o["spec"]["deviceRef"]["name"] = "r3"
    listed = config(render, "config-part9", "tunnels-part9", others + secrets())
    assert not any(e["exists"] for e in listed)


def test_a_router_with_no_section_lists_none(render):
    assert config(render, "config-absent", "tunnels-absent") == []


def test_no_list_before_the_router_is_read(render):
    rendered = render(KIND, copy.deepcopy(DEVICE), required=OBJECTS + secrets())
    assert "config" not in rendered.composite.get("status", {})


@pytest.mark.parametrize(
    "cfg, tunnels",
    [
        ("config-part9", None),
        (None, "tunnels-part9"),
        ("config-part9", ("tunnels-absent", 502)),
    ],
)
def test_no_list_until_both_reads_have_answered(render, cfg, tunnels):
    assert config(render, cfg, tunnels) is None


@pytest.mark.parametrize(
    "hostname, cfg, tunnels, want",
    [
        (True, "config-part9", "tunnels-part9", "True"),
        # A router with no section answers both reads with a 204.
        (True, "config-absent", "tunnels-absent", "True"),
        (False, "config-part9", "tunnels-part9", "False"),
        (True, None, "tunnels-part9", "False"),
        (True, "config-part9", None, "False"),
        (True, ("config-absent", 502), "tunnels-part9", "False"),
    ],
)
def test_ready_once_the_router_answers_and_both_reads_have(
    render, hostname, cfg, tunnels, want
):
    assert ready(device(render, hostname, cfg, tunnels)) == want
