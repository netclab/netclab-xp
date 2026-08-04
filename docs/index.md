# netclab-xp

A Crossplane Configuration package that turns router configuration into
Kubernetes resources — versioned, reviewable, and reconciled like anything else
in a cluster.

It targets devices that speak RESTCONF or JSON-RPC. Arista EOS is what it is
built and tested against today.

## The idea: layers, not one API

The same configuration can be expressed at several levels, and the package
offers all of them rather than picking one for you.

```
Fabric                     a whole network from one design
   ↓
Router                     one device, one resource
   ↓
BgpGlobal · BgpNeighbor · RoutedInterface · LoopbackInterface · …
   ↓
provider-http              RESTCONF · JSON-RPC · eAPI
```

Reading it from the bottom: the low-level resources map closely onto what a
device actually models, `Router` composes them into something you would
recognise as "a router", and `Fabric` describes a network and lets AVD work out
what each switch in it needs.

Which layer is right depends on what you are doing. Managing one setting on one
box is a low-level resource; standing up a fabric is not.

## What to read next

<div class="grid cards" markdown>

- **[Scenarios](scenarios/index.md)**

    Each mechanism the package offers, with manifests you can apply and what
    they do to a real device.

- **[Fabric walkthrough](scenarios/fabric.md)**

    One VLAN added to a design, and everything a fabric derives from it.

</div>

## Installing

Installation, the prerequisites, and the upgrade notes for 0.3.x live in the
[README](https://github.com/netclab/netclab-xp#getting-started). In short:

```bash
VERSION=<version>   # a tag from the Releases page

cat <<EOF | kubectl apply -f -
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: netclab-xp
spec:
  package: xpkg.upbound.io/netclab/netclab-xp:${VERSION}
EOF
```

!!! warning "Upgrading from 0.2.x is not in place"

    0.3.0 moved every XRD from `scope: Cluster` to `scope: Namespaced`, and
    `spec.scope` is immutable — so an installed Configuration cannot simply be
    pointed at it. Removing the old XRDs deletes the resources built on them,
    and that **takes the configuration off your devices**. Read
    [Upgrading from 0.2.x](https://github.com/netclab/netclab-xp#upgrading-from-02x)
    before you do it anywhere you care about.
