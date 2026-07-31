# Fabric — one model, a whole network

The other scenarios configure **one device at a time**. The `eos` layer does it
by hand, one XR per setting per device; the `mid` layer wraps that in a `Router`
abstraction, still one XR per device.

This one is the other end of that progression. A single `Fabric` describes the
*design* of a network — its tenants, VRFs, VLANs, uplinks — and AVD works out
what every switch in it must be configured with, then pushes that configuration
over eAPI.

It runs on its own devices, `dc1-spine1` and `dc1-leaf1a`, in the `avd`
namespace.

## Adding a VLAN

The whole scenario is one patch in `scenarios/fabric/kustomization.yaml`:

```yaml
- op: add
  path: /spec/design/tenants/0/vrfs/0/svis/-
  value:
    id: 13
    name: VRF10_VLAN13
    enabled: true
    ip_address_virtual: 10.10.13.1/24
```

Four lines describing an SVI in a tenant VRF. Here is what actually landed on
`dc1-leaf1a`:

```
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

The same VLAN at the `eos` layer is a hand-written XR per device, naming each
device and repeating what you already told it.

## Running it

```bash
WITH_FABRIC=1 scripts/up.sh
kubectl apply -k scenarios/fabric/prerequisites
kubectl apply -k scenarios/fabric
```

The prerequisites create the `avd` namespace, the eAPI credentials and a
`ProviderConfig`. They are separate from `scenarios/prerequisites/`, which the
other scenarios use — apply this one, not that one.

To see the model and the rendered configs:

```bash
kubectl apply -k scenarios/fabric --dry-run=client -o yaml   # the design
kubectl -n avd get fabric,cm -l avd.netclab.dev/device       # the render
```

`kubectl apply` returns long before anything reaches a device: the XR is
accepted immediately and its composed `Request`s do the work afterwards. Watch
those instead.

```bash
kubectl -n avd get requests.http.m.crossplane.io -w
```

An XR reports `Ready=False` for a poll interval after its Requests are already
`Ready=True`, often next to `Responsive=False WatchCircuitOpen`. It clears on
its own and is not worth debugging.

## Teardown leaves the device configured

```bash
kubectl delete -k scenarios/fabric
```

This removes the `Fabric`, its `Device`s, the rendered ConfigMaps and the
Requests — but **not the configuration on the switch**. After the delete,
`vlan 13`, its SVI and the widened trunk are all still on `dc1-leaf1a`.

That is intended. This scenario pushes a device's *entire* running
configuration, so a teardown that reverted it would wipe the switch. Crossplane
simply stops managing what it wrote.

To get a device back to its bootstrap state, restart its pod:

```bash
kubectl -n avd delete pod dc1-leaf1a
```

The startup-config is a ConfigMap and survives; everything pushed on top of it
does not.

Note this scenario differs from the others here: deleting the XRs of an `eos` or
`mid` scenario **does** strip the device.

## Two things to know before you run it

**The push replaces the whole running config**, and AVD renders nothing for
RESTCONF — so a pushed device loses netclab-chart's RESTCONF bootstrap until it
restarts. eAPI keeps working, because the model configures it. This is why the
fabric scenario has devices of its own and never touches `ceos01`/`ceos02`.

**Applying it needs network access.** The AVD design is not stored in this
repository; it is fetched from a tagged release of
[function-avd](https://github.com/netclab/function-avd), so an AVD upgrade
upstream changes nothing here until that tag is moved.
