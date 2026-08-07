# Fabric — one model, a whole network

The other scenarios configure **one device at a time**. The `eos` layer does it
by hand, one resource per setting per device; the `mid` layer wraps that in a
`Router`, still one resource per device.

This one is the other end of that progression. A single `Fabric` describes the
*design* of a network — its tenants, VRFs, VLANs, uplinks — and AVD works out
what every switch in it must be configured with, then pushes that configuration
over eAPI.

## The devices

It runs on `dc1-spine1` and `dc1-leaf1a`, in the `avd` namespace — two devices
of its own, because a push replaces a switch's entire running configuration and
would take over any device it is pointed at, including the ones from
[Set up a lab](../lab.md).

The cluster, Multus, the cEOS image and the chart are the ones you already have
from there. This is a second topology beside the first.

It is generated from the AVD model rather than written by hand, so fetch it from
the same tag the scenario reads, and install it into `avd`:

```bash
curl -sfL -o avd-topology.yaml \
  https://raw.githubusercontent.com/netclab/function-avd/v0.1.6/examples/lab/topology.yaml

helm upgrade --install avd netclab/netclab --version 0.5.11 \
  -n avd --create-namespace -f avd-topology.yaml
```

It names the same `ceos:4.36.1F` image you loaded in
[Set up a lab](../lab.md#the-ceos-image), so there is nothing to edit. Keep the
namespace, though — the scenario expects these devices in `avd`, and a
namespace holds one topology.

They take about two minutes to boot. Wait until both answer over eAPI, which is
what the push uses:

```bash
for n in dc1-spine1 dc1-leaf1a; do
  kubectl -n avd exec $n -- Cli -p 15 -c 'show management api http-commands' | head -2
done
```

```console
Enabled: Yes
HTTPS server: running, set to use port 443
```

## Running it

```bash
kubectl apply -k scenarios/fabric/prerequisites
kubectl apply -k scenarios/fabric
```

The prerequisites create the eAPI credentials and a `ProviderConfig`. They are
separate from `scenarios/prerequisites/`, which the other scenarios use — apply
this one, not that one.

Applying needs network access: the design is not stored in this repository, it
is fetched from a tagged release of
[function-avd](https://github.com/netclab/function-avd).

The `Fabric` is accepted immediately; the switches are configured by the
requests it composes. Watch those:

```bash
kubectl -n avd get requests.http.m.crossplane.io -w
```

## What lands on the switches

The design itself comes from function-avd. What this repository adds to it is
one patch in `scenarios/fabric/kustomization.yaml`:

```yaml
- op: add
  path: /spec/design/tenants/0/vrfs/0/svis/-
  value:
    id: 13
    name: VRF10_VLAN13
    enabled: true
    ip_address_virtual: 10.10.13.1/24
```

Four lines describing an SVI in a tenant VRF. From them AVD renders a whole
configuration for every switch in the design, and pushes it to the ones that are
running. The `Fabric` and one `Device` per switch record that:

```bash
kubectl -n avd get fabrics.avd.netclab.dev
kubectl -n avd get devices.avd.netclab.dev
```

```console
NAME             SYNCED   READY   COMPOSITION   AGE
single-dc-l3ls   True     True    fabric-avd    95s

NAME                              SYNCED   READY   COMPOSITION   AGE
single-dc-l3ls-dc1-leaf1a-fdb33   True     True    device-avd    95s
single-dc-l3ls-dc1-leaf1b-44015   True     True    device-avd    95s
single-dc-l3ls-dc1-leaf1c-18948   True     True    device-avd    95s
single-dc-l3ls-dc1-leaf2a-70ff8   True     True    device-avd    95s
single-dc-l3ls-dc1-leaf2b-89ff7   True     True    device-avd    95s
single-dc-l3ls-dc1-leaf2c-4d745   True     True    device-avd    95s
single-dc-l3ls-dc1-spine1-bf158   True     True    device-avd    95s
single-dc-l3ls-dc1-spine2-3a1a3   True     True    device-avd    95s
```

Eight of them, for a design of eight switches — you booted two. The `Fabric`
says as much, and says that pyavd accepted the model:

```bash
kubectl -n avd get fabrics.avd.netclab.dev single-dc-l3ls -o yaml \
  | yq '{"deviceCount": .status.deviceCount, "validation": .status.validation}'
```

```console
deviceCount: 8
validation:
  message: rendered
  ok: true
```

The six that are not running are rendered and nothing more: only the two hosts
named upstream in `spec.push.hosts` are given a `spec.push`, and only those two
are configured. Each of them records what the switch confirmed:

```bash
kubectl -n avd get devices.avd.netclab.dev -l avd.netclab.dev/device=dc1-leaf1a \
  -o jsonpath='{.items[0].status.push}' | yq -P .
```

```console
configHash: sha256:971d986cf5faeaee
digest: 784d254cd6c27c6b9e2d42b48a86a73e7bf0ebd7
lastDeployedTime: "2026-08-07T12:40:43+00:00"
```

`configHash` identifies the render the device should be running, `digest` is what
the device confirmed receiving, and `lastDeployedTime` moves only when the
configuration actually changed. Select by label rather than by name — the
`Device` names carry a generated suffix.

This is what reached `dc1-leaf1a`, scattered through its running config:

```bash
kubectl -n avd exec dc1-leaf1a -- Cli -p 15 -c "show running-config"
```

```console
vlan 13
   name VRF10_VLAN13
interface Vlan13
   description VRF10_VLAN13
   vrf VRF10
   ip address virtual 10.10.13.1/24
interface Port-Channel8
   switchport trunk allowed vlan 11-13,21-22,3401-3402
interface Vxlan1
   vxlan vlan 13 vni 10013
router bgp 65101
   vlan 13
      rd 10.255.0.3:10013
      route-target both 10013:10013
```

The VXLAN VNI, the EVPN route-target, the route distinguisher and the widened
trunk list were none of them written down. Neither was the decision about
*where* the VLAN belongs: `dc1-spine1` received the push too, and has no
`vlan 13` at all, because a tenant SVI belongs on leaves.

The same VLAN at the `eos` layer is a hand-written resource per device, naming
each device and repeating what you already told it.

## Teardown leaves the device configured

```bash
kubectl delete -k scenarios/fabric
```

This removes the `Fabric`, its `Device`s, the rendered ConfigMaps and the
requests — but **not the configuration on the switch**. After the delete,
`vlan 13`, its SVI and the widened trunk are all still on `dc1-leaf1a`.

That is intended, and it is the opposite of every other scenario here, where
deleting a resource strips the device. This one pushes a switch's entire
configuration, so a teardown that reverted it would wipe the switch. Crossplane
stops managing what it wrote and leaves it running.

To get a device back to its bootstrap state, restart its pod — the
startup-config is a ConfigMap and survives, everything pushed on top of it does
not:

```bash
kubectl -n avd delete pod dc1-leaf1a
```

!!! tip "Working on the package itself?"

    `WITH_FABRIC=1 scripts/up.sh` builds the cluster and both topologies in one
    command, with the package built from your working tree. That is a
    contributor tool, not the path described here.
