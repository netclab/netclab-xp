"""Device: spec.config composed in order, one object more each time the one above is Ready,
and the schema of each object kept to the spec of its kind."""

import copy
import subprocess

import pytest
import yaml
from conftest import IOSXE, in_namespace, observed

# The order part 9 applies the examples in.
KINDS = [
    "ikev2proposal",
    "ikev2policy",
    "ikev2keyring",
    "ikev2profile",
    "ipsectransformset",
    "ipsecprofile",
    "tunnelinterface",
]
IDS = [
    "ikev2proposal-classical-proposal",
    "ikev2policy-classical-policy",
    "ikev2keyring-classical-keyring",
    "ikev2profile-classical-profile",
    "ipsectransformset-classical-ts",
    "ipsecprofile-classical-ipsec",
    "tunnelinterface-tunnel0",
]


def key(kind):
    return kind[0].lower() + kind[1:]


def example(kind):
    return yaml.safe_load((IOSXE / "examples" / kind / "r1.yaml").read_text())


def device():
    """The example Device r1, its config the examples of r1 without their deviceRef."""
    xr = in_namespace(IOSXE / "examples" / "device" / "r1.yaml")
    xr["spec"]["config"] = []
    for kind in KINDS:
        doc = example(kind)
        del doc["spec"]["deviceRef"]
        xr["spec"]["config"].append({key(doc["kind"]): doc["spec"]})
    return xr


def composed(rendered):
    """The ids of the config objects a render composes, in their order."""
    return [i for i in IDS if i in rendered.resources]


@pytest.fixture(scope="module")
def stages(render):
    """Render n has the first n objects of the config composed before and Ready, and the
    hostname Request with them from the second on."""
    out = []
    before = {}
    for n in range(len(IDS) + 1):
        ready = [before[i] for i in IDS[:n]]
        if n:
            ready.append(before["hostname"])
        rendered = render("device", device(), [observed(r, True) for r in ready])
        before.update(rendered.resources)
        out.append(rendered)
    return out


@pytest.mark.parametrize("n", range(len(IDS) + 1))
def test_composes_the_next_once_the_ones_above_are_ready(stages, n):
    assert composed(stages[n]) == IDS[: min(n + 1, len(IDS))]


@pytest.mark.parametrize("n", range(len(IDS) + 1))
def test_counts_the_ready_ones(stages, n):
    assert stages[n].composite["status"]["config"] == f"{n}/{len(IDS)}"


@pytest.mark.parametrize(
    ("n", "ready"), [(0, "False"), (len(IDS) - 1, "False"), (len(IDS), "True")]
)
def test_is_ready_once_the_whole_config_is(stages, n, ready):
    conditions = {
        c["type"]: c["status"] for c in stages[n].composite["status"]["conditions"]
    }
    assert conditions["Ready"] == ready


def test_keeps_an_object_it_composed_when_one_above_is_not_ready(stages, render):
    first, second, third = (stages[-1].resources[i] for i in IDS[:3])
    before = [observed(first, True), observed(second, False), observed(third, False)]
    assert composed(render("device", device(), before)) == IDS[:3]


def test_composes_each_object_as_its_kind_with_the_device(stages):
    for kind, i in zip(KINDS, IDS, strict=True):
        doc = example(kind)
        resource = stages[-1].resources[i]
        assert (resource["apiVersion"], resource["kind"]) == (
            doc["apiVersion"],
            doc["kind"],
        )
        assert resource["spec"] == doc["spec"]


def test_names_an_object_by_its_kind_and_its_name_on_the_router(stages, render):
    # One more proposal on top of a config all Ready: the others keep their ids.
    xr = device()
    extra = copy.deepcopy(xr["spec"]["config"][0])
    extra["ikev2Proposal"]["name"] = "Other_Proposal"
    xr["spec"]["config"].insert(0, extra)
    before = [observed(r, True) for r in stages[-1].resources.values()]
    resources = render("device", xr, before).resources
    assert sorted(resources) == sorted(
        ["hostname", "ikev2proposal-other-proposal", *IDS]
    )


def test_refuses_an_object_listed_twice(render):
    xr = device()
    xr["spec"]["config"].append(copy.deepcopy(xr["spec"]["config"][0]))
    with pytest.raises(subprocess.CalledProcessError) as error:
        render("device", xr)
    assert (
        "spec.config lists Ikev2Proposal CLASSICAL-PROPOSAL twice" in error.value.stderr
    )


def test_config_takes_the_spec_of_each_kind_but_its_device():
    xrd = yaml.safe_load((IOSXE / "apis" / "device" / "xrd.yaml").read_text())
    spec = xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]
    items = spec["properties"]["config"]["items"]["properties"]
    assert list(items) == [key(example(kind)["kind"]) for kind in KINDS]
    for kind in KINDS:
        kind_xrd = yaml.safe_load((IOSXE / "apis" / kind / "xrd.yaml").read_text())
        name = kind_xrd["spec"]["names"]["kind"]
        kind_spec = kind_xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"][
            "properties"
        ]
        expected = copy.deepcopy(kind_spec["spec"])
        del expected["properties"]["deviceRef"]
        expected["required"].remove("deviceRef")
        expected["description"] = f"The fields of the spec of {name} but deviceRef."
        assert items[key(name)] == expected, name
