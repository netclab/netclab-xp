"""Ikev2Keyring: the checks its Requests observe with, on the router's recorded answers."""

import json

import pytest
from conftest import check, recorded

KIND = "ikev2keyring"
XR = "r1-ikev2-keyring"


@pytest.mark.parametrize(
    ("state", "up_to_date"),
    [
        ("keyring-unmarked", True),
        # The PPK mark on the peer is not the keyring Request's drift.
        ("keyring-applied", True),
        ("keyring-other-psk", False),
        ("keyring-absent", False),
    ],
)
def test_keyring_compares_only_what_it_sets(rendered, state, up_to_date):
    keyring = rendered[XR]["keyring"]
    result = check(keyring, "expectedResponseCheck", recorded(KIND, state))
    assert result is up_to_date


@pytest.mark.parametrize(
    ("state", "removed"),
    [
        ("peer-marked", False),
        ("peer-unmarked", True),
        ("peer-old-mark", True),
        ("peer-absent", True),
    ],
)
def test_ppk_is_absent_without_its_mark(rendered, state, removed):
    ppk = rendered[XR]["ppk-r3"]
    assert check(ppk, "isRemovedCheck", recorded(KIND, state)) is removed


def test_ppk_survives_a_router_error(rendered):
    # Taken for absent, the PPK would be applied again and the peer's SA cleared.
    ppk = rendered[XR]["ppk-r3"]
    assert check(ppk, "isRemovedCheck", {"statusCode": 502, "body": ""}) is False


def test_ppk_mark_follows_the_key_and_the_clear_comes_last(rendered):
    # A rejected key stops the RPC at its line: no mark, and the SA is left alone.
    body = json.loads(rendered[XR]["ppk-r3"]["spec"]["forProvider"]["payload"]["body"])
    lines = [
        line.strip()
        for line in body["Cisco-IOS-XE-cli-rpc:input"]["config-clis"].splitlines()
    ]
    key = next(i for i, line in enumerate(lines) if line.startswith("ppk manual"))
    assert lines.index("description ppk PPK-R1R3") == key + 1
    assert lines[-1] == "do clear crypto ikev2 sa remote 10.0.23.2"
