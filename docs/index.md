# netclab-xp

A Crossplane Configuration package that turns router configuration into
Kubernetes resources — versioned, reviewable, and reconciled like anything else
in a cluster.

It targets devices that speak RESTCONF or JSON-RPC. Arista EOS is what it is
built and tested against today.

## The idea: layers, not one API

The same configuration can be expressed at more than one level, and the package
offers both rather than picking for you.

```
Router                                          one device, one resource
   ↓
BgpGlobal · BgpNeighbor · BgpPeerGroup ·        one setting, one resource
RoutedInterface · LoopbackInterface ·
IpRouting · EosCommand · …
   ↓
provider-http                                   RESTCONF · JSON-RPC · eAPI
```

Reading from the bottom: the low-level resources map closely onto what a device
actually models, and `Router` composes them into something you would recognise
as "a router". Twelve resource types ship in the package, all in the
`eos.netclab.dev` API group.

Which layer is right depends on what you are doing. Managing one setting on one
box is a low-level resource; describing a whole router is not.

!!! info "`Fabric` is a level above, and lives elsewhere"

    The [fabric scenario](scenarios/fabric.md) describes an entire network from
    one AVD design. Its API is **not** part of this package — it ships in
    `configuration-avd`, which netclab-xp pulls in as a dependency. So you will
    not find a `Fabric` resource type under `eos.netclab.dev`.

## Getting started

<div class="grid cards" markdown>

- **[Set up a lab](lab.md)**

    Two cEOS devices on Kubernetes, which every scenario here is written
    against.

- **[Install the package](install.md)**

    The Configuration, its prerequisites, and the 0.2.x upgrade hazards.

- **[Your first resource](first-resource.md)**

    One interface, then one router, then a BGP session between two devices.

- **[Scenarios](scenarios/index.md)**

    Each mechanism the package offers, with manifests you can apply and what
    they do to a real device.

- **[Fabric walkthrough](scenarios/fabric.md)**

    One VLAN added to a design, and everything a fabric derives from it.

</div>
