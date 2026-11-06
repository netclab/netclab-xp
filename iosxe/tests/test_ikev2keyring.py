"""Ikev2Keyring: its name, its modes, the checks its Requests observe with on the router's
recorded answers, the key Requests composed after the keyring, their marks, the keyring's
origin, and missing Secrets."""

import json
import re
from functools import partial

import pytest
from conftest import (
    DEVICES,
    IOSXE,
    _secrets,
    check,
    in_namespace,
    observed,
    recorded,
    requests,
    secrets,
    status,
)
from conftest import answered as _answered

KIND = "ikev2keyring"
XR = "r1--classical-keyring--eb60cb7d"
answered = partial(_answered, KIND)
KEYS = ["psk-r3", "ppk-r3"]
VALUES = {
    "ike-keys": {"psk": "TestPsk123", "ppk-hex": "48656C6C6F506F737451756172746E756D"}
}


def example(policy="Replace", origin="Created"):
    """The example in `policy`, with `origin` in its status: until then nothing writes."""
    xr = in_namespace(IOSXE / "examples" / KIND / "r1.yaml")
    if policy:
        xr["spec"]["managementPolicy"] = policy
    else:
        del xr["spec"]["managementPolicy"]
    if origin:
        xr["status"] = {"origin": origin}
    return xr


def thin(xr_name=XR):
    """An object as Step 3 imports it: deviceRef and name, no mode."""
    return {
        "apiVersion": "iosxe.netclab.dev/v1alpha1",
        "kind": "Ikev2Keyring",
        "metadata": {"name": xr_name, "namespace": "lab"},
        "spec": {"deviceRef": {"name": "r1"}, "name": "CLASSICAL-KEYRING"},
    }


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
    assert requests(rendered.resources) == []
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
    assert requests(rendered.resources) == sorted(["keyring", *KEYS])
    for key in KEYS:
        assert rendered.resources[key]["spec"] == composed[key]["spec"]
    assert ready(rendered) == "False"


def test_missing_key_is_named(render):
    rendered = with_keys(render, values={"ike-keys": {"psk": "TestPsk123"}})
    assert rendered.composite["status"]["missingSecrets"] == ["ike-keys/ppk-hex"]
    assert requests(rendered.resources) == ["keyring", "psk-r3"]


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
    assert requests(render(KIND, example(), seen).resources) == sorted(composed)


def first(render, xr):
    return render(KIND, xr, required=DEVICES + secrets(VALUES)).resources


def after_get(render, xr, state):
    """The XR rendered with its keyring's Request answered by a GET in `state`."""
    request = first(render, xr)["keyring"]
    return render(KIND, xr, [answered(request, state)], DEVICES + secrets(VALUES))


def test_an_object_under_another_name_composes_nothing(render):
    xr = thin("my-keyring")
    rendered = render(KIND, xr, required=DEVICES)
    assert rendered.resources == {}
    assert rendered.composite["status"]["wantsName"] == XR
    assert ready(rendered) == "False"


@pytest.mark.parametrize(
    ("policy", "policies", "writes"),
    [
        (None, ["Observe"], []),
        (
            "Merge",
            ["Observe", "Create", "Update"],
            [("CREATE", "PATCH"), ("UPDATE", "PATCH")],
        ),
        (
            "Replace",
            ["*"],
            [("CREATE", "PUT"), ("UPDATE", "PUT"), ("REMOVE", "DELETE")],
        ),
    ],
)
def test_the_mode_decides_what_the_request_may_do(render, policy, policies, writes):
    spec = first(render, example(policy))["keyring"]["spec"]
    assert spec["managementPolicies"] == policies
    assert [
        (m["action"], m["method"])
        for m in spec["forProvider"]["mappings"]
        if m["action"] != "OBSERVE"
    ] == writes


def test_merge_sends_the_patch_the_router_merged_without_keys(render):
    for_provider = first(render, example("Merge"))["keyring"]["spec"]["forProvider"]
    sent = recorded(KIND, "keyring-patch")["request"]
    assert json.loads(for_provider["payload"]["body"]) == sent["body"]
    writes = [m for m in for_provider["mappings"] if m["action"] != "OBSERVE"]
    assert {(m["method"], json.loads(m["url"])) for m in writes} == {
        (sent["method"], sent["url"])
    }


def test_replace_puts_the_psk_the_router_then_returns(render):
    body = first(render, example())["keyring"]["spec"]["forProvider"]["payload"]["body"]
    assert json.loads(_secrets(body)) == recorded(KIND, "keyring-applied")["body"]


@pytest.mark.parametrize(
    ("state", "merge", "replace"),
    [
        ("keyring-applied", True, True),
        # A key's value is never compared: the router may give it back encrypted.
        ("keyring-other-psk", True, True),
        ("keyring-patched", True, True),
        # A peer's description: Merge leaves it, Replace takes it off.
        ("keyring-described", True, False),
        # Replace's PUT carries the PSK; Merge leaves keys alone.
        ("keyring-no-psk", True, False),
        ("keyring-absent", False, False),
    ],
)
def test_check_is_the_mode_write_changing_nothing(render, state, merge, replace):
    for policy, expected in [("Merge", merge), ("Replace", replace)]:
        request = first(render, example(policy))["keyring"]
        assert (
            check(request, "expectedResponseCheck", recorded(KIND, state)) is expected
        )


@pytest.mark.parametrize("policy", ["Merge", "Replace"])
def test_until_the_origin_is_known_the_keyring_is_only_read(render, policy):
    # A write that creates the keyring would leave no GET to tell the origin by.
    composed = first(render, example(policy, origin=None))
    assert composed["keyring"]["spec"]["managementPolicies"] == ["Observe"]
    names = composed["origin"]["spec"]
    assert names["managementPolicies"] == ["Observe"]
    assert names["forProvider"]["payload"]["baseUrl"].endswith(
        "/crypto?fields=Cisco-IOS-XE-crypto:ikev2/keyring/name"
    )
    assert "origin" not in first(render, example(None, origin=None))


@pytest.mark.parametrize(
    ("state", "origin"),
    [
        ("origin-absent", "Created"),
        ("origin-other", "Created"),
        ("origin-applied", "TakenOver"),
    ],
)
def test_the_names_tell_the_origin_then_the_keyring_is_written(render, state, origin):
    xr = example("Replace", origin=None)
    before = [answered(first(render, xr)["origin"], state)]
    rendered = render(KIND, xr, before, DEVICES + secrets(VALUES))
    assert status(rendered)["origin"] == origin
    assert "origin" not in rendered.resources
    assert rendered.resources["keyring"]["spec"]["managementPolicies"] == ["*"]


def test_a_keyring_read_there_is_taken_over_and_the_origin_stays(render):
    xr = example(None, origin=None)
    assert status(after_get(render, xr, "keyring-applied"))["origin"] == "TakenOver"
    # Whatever the router shows later.
    xr = example(None, origin="Created")
    assert status(after_get(render, xr, "keyring-applied"))["origin"] == "Created"


def keys_after(render, xr, keyring, origin, marks=None):
    """The key Requests of `xr` with its keyring's GET in `keyring`, `origin` set, and the
    key's own last read in `marks` (by key, a recorded state), or none."""
    xr["status"] = {"origin": origin}
    composed = first(render, xr)
    before = [answered(composed["keyring"], keyring)]
    rendered = render(KIND, xr, before, DEVICES + secrets(VALUES)).resources
    for key, state in (marks or {}).items():
        before.append(answered(rendered[key], state))
    if marks:
        rendered = render(KIND, xr, before, DEVICES + secrets(VALUES)).resources
    return rendered


def body(request):
    return json.loads(request["spec"]["forProvider"]["payload"]["body"])


@pytest.mark.parametrize("key", ["psk", "ppk"])
def test_taking_over_writes_only_the_mark_of_a_key_the_router_holds(render, key):
    rendered = keys_after(render, example("Merge"), "keyring-applied", "TakenOver")
    assert (
        body(rendered[f"{key}-r3"])
        == recorded(KIND, f"{key}-mark-rpc")["request"]["body"]
    )


def test_taking_over_writes_a_psk_the_router_lacks(render):
    rendered = keys_after(render, example("Merge"), "keyring-no-psk", "TakenOver")
    clis = body(rendered["psk-r3"])["Cisco-IOS-XE-cli-rpc:input"]["config-clis"]
    assert " pre-shared-key {{ ike-keys:lab:psk }}" in clis.splitlines()[2]


@pytest.mark.parametrize(
    ("origin", "marks"),
    [
        # A keyring the package created gets its keys.
        ("Created", {}),
        # A mark that differs writes the key whatever the origin.
        ("TakenOver", {"psk-r3": "psk-mark-other", "ppk-r3": "ppk-mark-other"}),
    ],
)
def test_the_key_is_written_with_its_mark_and_the_clear(render, origin, marks):
    rendered = keys_after(render, example("Merge"), "keyring-applied", origin, marks)
    for key in KEYS:
        clis = body(rendered[key])["Cisco-IOS-XE-cli-rpc:input"]["config-clis"]
        assert clis.splitlines()[-1] == "do clear crypto ikev2 sa remote 10.0.23.2"


@pytest.mark.parametrize(("policy", "removes"), [("Merge", False), ("Replace", True)])
def test_only_replace_removes_a_key(render, policy, removes):
    rendered = keys_after(render, example(policy), "keyring-applied", "Created")
    for key in KEYS:
        actions = [
            m["action"] for m in rendered[key]["spec"]["forProvider"]["mappings"]
        ]
        assert ("REMOVE" in actions) is removes


@pytest.mark.parametrize(("policy", "held"), [("Merge", False), ("Replace", True)])
def test_replace_deletes_the_keyring_only_after_the_ppk_line(render, policy, held):
    # A PPK's removal enters the keyring, which would make it again once deleted.
    composed = with_keys(render, example(policy)).resources
    before = [observed(composed[r], True) for r in ["keyring", *KEYS]]
    resources = render(
        KIND, example(policy), before, DEVICES + secrets(VALUES)
    ).resources
    usage = resources.get("keyring-by-ppk-r3")
    assert (usage is not None) is held
    # A PSK's removal deletes its mark alone.
    assert "keyring-by-psk-r3" not in resources
    if held:
        assert usage["spec"]["of"]["resourceRef"] == {
            "name": before[0]["metadata"]["name"]
        }
        assert usage["spec"]["by"]["resourceRef"] == {
            "name": before[2]["metadata"]["name"]
        }
        assert usage["spec"]["replayDeletion"] is True


@pytest.mark.parametrize("previous", ["Merge", "Replace"])
def test_back_in_observe_a_key_s_request_stays_and_only_reads(render, previous):
    # Dropped, a Request composed in Replace would be deleted with its REMOVE, and
    # the key and its mark taken off the router.
    composed = with_keys(render, example(previous)).resources
    before = [observed(r, True) for r in composed.values()]
    rendered = render(KIND, example(None), before, DEVICES + secrets(VALUES))
    assert requests(rendered.resources) == sorted(["keyring", *KEYS])
    for key in KEYS:
        spec = rendered.resources[key]["spec"]
        assert spec["managementPolicies"] == ["Observe"]
        assert spec["forProvider"] == composed[key]["spec"]["forProvider"]


def test_observe_writes_no_key_and_needs_no_secret(render):
    rendered = render(KIND, example(None), required=DEVICES)
    assert requests(rendered.resources) == ["keyring"]
    assert rendered.composite["status"]["missingSecrets"] == []


def test_a_thin_object_shows_a_key_only_as_there(render):
    rendered = after_get(render, thin(), "keyring-applied")
    assert status(rendered)["observed"] == {
        "peers": [
            {"name": "R3", "address": "10.0.23.2", "preSharedKey": {"present": True}}
        ]
    }
    assert status(rendered)["drift"] == [] and status(rendered)["extra"] == []
    assert ready(rendered) == "True"


@pytest.mark.parametrize(
    ("policy", "state", "drift", "extra"),
    [
        ("Merge", "keyring-described", [], []),
        (
            "Replace",
            "keyring-described",
            [],
            [{"field": "peers[R3].description", "device": ['"made by hand"']}],
        ),
        ("Merge", "keyring-no-psk", [], []),
        (
            "Replace",
            "keyring-no-psk",
            [{"field": "peers[R3].preSharedKey", "device": [], "spec": ["present"]}],
            [],
        ),
        (
            "Merge",
            "keyring-absent",
            [],
            [],
        ),
    ],
)
def test_drift_and_extra_follow_the_mode(render, policy, state, drift, extra):
    rendered = after_get(render, example(policy), state)
    assert status(rendered).get("drift", []) == drift
    assert status(rendered).get("extra", []) == extra
