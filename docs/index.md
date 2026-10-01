# netclab-xp

A Crossplane Configuration package that turns router configuration into
Kubernetes resources — versioned, reviewable, and reconciled like anything else
in a cluster.

It targets devices that speak RESTCONF or JSON-RPC. Arista EOS is what it is
built and tested against today.

## One API for you, several mechanisms for the device

Everything here is a Kubernetes resource. You apply it, review it in a pull
request and keep it in git the same way whatever the device on the other end
speaks. That is the whole point: one workflow, one API surface, one place the
intended state lives.

Underneath, RESTCONF carries structured data and reaches what OpenConfig models;
eAPI carries CLI commands over JSON-RPC, so it reaches whatever the CLI can say
— including plenty that OpenConfig does not model. The two overlap heavily, and
the [scenarios](scenarios/index.md) are organised around that split.

Where they overlap, the mechanism is a choice you can make **without changing
the resource**. `BgpGlobal` has one composition per mechanism, selected by a
label:

```yaml
spec:
  crossplane:
    compositionSelector:
      matchLabels:
        eos.netclab.dev/mechanism: jsonrpc   # omit this and you get RESTCONF
```

## How much you describe at once

A separate question from mechanism, and the one the layers answer. Installing
the package gives you all of its own rather than picking for you.

```
Fabric — in function-avd, installed apart       a whole network, one design
   ↓
Router                                          one device, one resource
   ↓
BgpGlobal · BgpNeighbor · BgpPeerGroup ·        one setting, one resource
RoutedInterface · LoopbackInterface ·
IpRouting · EosCommand · …
   ↓
provider-http                                   RESTCONF · JSON-RPC · eAPI
```

Reading from the bottom: the low-level resources map closely onto what a device
actually models. `Router` composes them into something you would recognise as "a
router". `Fabric` goes a level further again — it describes the *design* of a
network, and AVD works out what every switch in it must be configured with. It
is [function-avd](https://github.com/netclab/function-avd)'s, and not installed
with this package.

Which layer is right depends on what you are doing. Managing one setting on one
box is a low-level resource; standing up a fabric is not.

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

</div>
