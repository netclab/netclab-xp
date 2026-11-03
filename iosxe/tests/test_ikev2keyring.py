"""Ikev2Keyring: the checks its Requests observe with, on the router's recorded answers, the
key Requests composed after the keyring, their marks, and missing Secrets."""

import json
import re

import pytest
from conftest import EXAMPLES, IOSXE, check, in_namespace, observed, recorded, secrets

KIND = "ikev2keyring"
XR = "r1-ikev2-keyring"
KEYS = ["psk-r3", "ppk-r3"]
DEVICES = [in_namespace(p) for p in EXAMPLES if p.parent.name == "device"]
VALUES = {
    "ike-keys": {"psk": "TestPsk123", "ppk-hex": "48656C6C6F506F737451756172746E756D"}
}


def example():
    return in_namespace(IOSXE / "examples" / KIND / "r1.yaml")


def with_keys(render, xr=None, values=VALUES, uid=None, before=None):
    """The example rendered with its keyring composed and Ready, and these Secrets."""
    required = secrets(values)
    if uid:
        for s in required:
            s["metadata"]["uid"] = uid
    seen = before if before is not None else [observed(keyring(render), True)]
    return render(KIND, xr or example(), seen, DEVICES + required)


def keyring(render):
    return render(KIND, example()).resources["keyring"]


def mark(request):
    logic = request["spec"]["forProvider"]["expectedResponseCheck"]["logic"]
    return re.search(r'== "([0-9a-f]{8})"', logic).group(1)


def ready(rendered):
    conditions = rendered.composite["status"]["conditions"]
    return {c["type"]: c["status"] for c in conditions}["Ready"]


@pytest.mark.parametrize(
    ("state", "up_to_date"),
    [
        ("keyring-applied", True),
        # A description and a PPK line set by hand are not the keyring's to compare.
        ("keyring-described", True),
        # The router may give a PSK back encrypted: only that it is there counts.
        ("keyring-other-psk", True),
        ("keyring-no-psk", False),
        ("keyring-absent", False),
    ],
)
def test_keyring_checks_that_a_psk_is_there_not_its_value(rendered, state, up_to_date):
    result = check(
        rendered[XR]["keyring"], "expectedResponseCheck", recorded(KIND, state)
    )
    assert result is up_to_date


@pytest.mark.parametrize("key", ["psk", "ppk"])
@pytest.mark.parametrize(
    ("state", "removed", "up_to_date"),
    [
        ("mark-absent", True, False),
        ("mark-applied", False, True),
        ("mark-other", False, False),
    ],
)
def test_key_is_up_to_date_only_with_its_mark(
    rendered, key, state, removed, up_to_date
):
    request = rendered[XR][f"{key}-r3"]
    response = recorded(KIND, f"{key}-{state}")
    assert check(request, "isRemovedCheck", response) is removed
    assert check(request, "expectedResponseCheck", response) is up_to_date


@pytest.mark.parametrize("key", KEYS)
def test_key_survives_a_router_error(rendered, key):
    # Taken for absent, the key would be written again, and a PPK's SA cleared.
    assert (
        check(rendered[XR][key], "isRemovedCheck", {"statusCode": 502, "body": ""})
        is False
    )


@pytest.mark.parametrize(
    ("key", "line"),
    [
        ("psk-r3", "pre-shared-key {{ ike-keys:lab:psk }}"),
        (
            "ppk-r3",
            "ppk manual id PPK-R1R3 key hex {{ ike-keys:lab:ppk-hex }} required",
        ),
    ],
)
def test_rpc_writes_the_key_then_the_mark_then_clears(rendered, key, line):
    # A refused key stops the RPC at its line: no mark, and the SA is left alone. The
    # clear puts the key in use: an SA in place would go on without it.
    request = rendered[XR][key]["spec"]["forProvider"]
    body = json.loads(request["payload"]["body"])
    lines = [
        line.strip()
        for line in body["Cisco-IOS-XE-cli-rpc:input"]["config-clis"].splitlines()
    ]
    at = lines.index(line)
    assert lines[at + 1 : at + 3] == ["exit", "exit"]
    variable = lines[at + 3].split(" ")[3]
    assert lines[at + 3].startswith(
        f'event manager environment {variable} "{mark(rendered[XR][key])} '
    )
    assert request["payload"]["baseUrl"].endswith(f"/environment={variable}")
    assert lines[-1] == "do clear crypto ikev2 sa remote 10.0.23.2"
    writes = [m for m in request["mappings"] if m["action"] in ("CREATE", "UPDATE")]
    assert [(m["method"], m["body"]) for m in writes] == [("POST", ".payload.body")] * 2


@pytest.fixture(scope="module")
def marks(render):
    """The marks of both keys, by what was changed from the example."""

    def _marks(**change):
        xr = example()
        values = json.loads(json.dumps(VALUES))
        if "psk" in change:
            values["ike-keys"]["psk"] = change["psk"]
        if "ppk" in change:
            values["ike-keys"]["ppk-hex"] = change["ppk"]
        if "id" in change:
            xr["spec"]["peers"][0]["ppk"]["id"] = change["id"]
        if "rewrite" in change:
            xr["metadata"]["annotations"] = {
                "iosxe.netclab.dev/rewrite-keys": change["rewrite"]
            }
        rendered = with_keys(render, xr, values, change.get("uid"))
        return {k.split("-")[0]: mark(rendered.resources[k]) for k in KEYS}

    return _marks


@pytest.mark.parametrize(
    ("change", "changed"),
    [
        ({}, set()),
        # A key changed in a Secret writes that key alone, not the one beside it.
        ({"psk": "OtherPsk456"}, {"psk"}),
        ({"ppk": "476F6F646279655175616E74756D4B6579"}, {"ppk"}),
        ({"id": "PPK-R1R3-2"}, {"ppk"}),
        # A Secret made again, or the annotation, writes every key once.
        ({"uid": "00000000-0000-4000-8000-000000000002"}, {"psk", "ppk"}),
        ({"rewrite": "2026-11-03"}, {"psk", "ppk"}),
    ],
)
def test_mark_changes_with_the_key_and_nothing_else(marks, change, changed):
    before, after = marks(), marks(**change)
    assert {k for k in before if before[k] != after[k]} == changed


def test_missing_secret_composes_nothing_new(render):
    rendered = render(KIND, example(), required=DEVICES)
    assert rendered.resources == {}
    assert rendered.composite["status"]["missingSecrets"] == [
        "ike-keys/psk",
        "ike-keys/ppk-hex",
    ]
    assert ready(rendered) == "False"


def test_missing_secret_keeps_what_was_composed(render):
    # Dropped, a Request would be deleted, and with it the key on the router.
    composed = with_keys(render).resources
    before = [observed(r, True) for r in composed.values()]
    rendered = render(KIND, example(), before, DEVICES)
    assert sorted(rendered.resources) == sorted(["keyring", *KEYS])
    for key in KEYS:
        assert rendered.resources[key]["spec"] == composed[key]["spec"]
    assert ready(rendered) == "False"


def test_missing_key_is_named(render):
    rendered = with_keys(render, values={"ike-keys": {"psk": "TestPsk123"}})
    assert rendered.composite["status"]["missingSecrets"] == ["ike-keys/ppk-hex"]
    assert sorted(rendered.resources) == ["keyring", "psk-r3"]


@pytest.mark.parametrize(("key_ready", "written"), [(True, True), (False, False)])
def test_written_follows_the_key_request(render, key_ready, written):
    composed = with_keys(render).resources
    before = [observed(composed["keyring"], True)]
    before += [observed(composed[k], key_ready) for k in KEYS]
    keys = with_keys(render, before=before).composite["status"]["keys"]
    assert keys == [
        {"path": "peers[R3].preSharedKey", "written": written},
        {"path": "peers[R3].ppk", "written": written},
    ]


@pytest.mark.parametrize(
    ("before", "composed"),
    [
        # Nothing composed yet, or the keyring not Ready: the keyring alone.
        ({}, ["keyring"]),
        ({"keyring": False}, ["keyring"]),
        # The keyring Ready: the keys with it.
        ({"keyring": True}, ["keyring", *KEYS]),
        # A key composed before stays, whatever the keyring does.
        ({"keyring": False, "psk-r3": False, "ppk-r3": False}, ["keyring", *KEYS]),
    ],
)
def test_keys_wait_for_the_keyring(rendered, render, before, composed):
    seen = [observed(rendered[XR][name], ready) for name, ready in before.items()]
    assert sorted(render(KIND, example(), seen).resources) == sorted(composed)
