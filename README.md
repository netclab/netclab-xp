# netclab-xp, routers operated from Kubernetes

> ***Extend Kubernetes to manage any resource anywhere***
> <br>Powered by [crossplane.io](https://www.crossplane.io)

**Crossplane Configuration packages that operate routers from Kubernetes.**

They turn router settings into Kubernetes resources: declarative, versioned,
reviewable, and reconciled like anything else in a cluster.

| package | devices | over | tags |
|---|---|---|---|
| `configuration-iosxe` | Cisco IOS XE | RESTCONF | `iosxe/v*` |
| `configuration-eos` | Arista EOS | RESTCONF, JSON-RPC (eAPI) | `eos/v*` |

Until `v0.5.0` the EOS package was published as `netclab-xp`; those releases stay
where they are.

## Documentation

**[netclab.dev/netclab-xp](https://netclab.dev/netclab-xp/)**

| | |
|---|---|
| [Post-quantum IPsec on IOS XE](https://netclab.dev/netclab-xp/iosxe/) | an IPsec tunnel with a post-quantum preshared key, kept on the routers |
| [Arista EOS](https://netclab.dev/netclab-xp/eos/) | one API over several mechanisms |
| [Set up a lab](https://netclab.dev/netclab-xp/eos/lab/) | two cEOS devices on Kubernetes |
| [Install the package](https://netclab.dev/netclab-xp/eos/install/) | the Configuration and its prerequisites |
| [Your first resource](https://netclab.dev/netclab-xp/eos/first-resource/) | one interface, then a BGP session between two devices |
| [Scenarios](https://netclab.dev/netclab-xp/eos/scenarios/) | every mechanism the package offers |

## Cisco IOS XE

One resource type per router setting in `iosxe.netclab.dev`, over RESTCONF:
`Device`, `Ikev2Proposal`, `Ikev2Policy`, `Ikev2Keyring` (with a post-quantum
preshared key), `Ikev2Profile`, `IpsecTransformSet`, `IpsecProfile` and
`TunnelInterface`. Each waits for the objects it names, so a set applies at once.

[`iosxe/scenarios/part9/`](iosxe/scenarios/part9/) is part 9 of
[Cisco's IPsec series](https://blogs.cisco.com/developer/post-quantum-key-exchange-on-cisco-routers-ipsec-series-part-9):
Tunnel0 between two routers, with a post-quantum preshared key (PPK, RFC 8784) mixed
into IKEv2, kept on the routers by reconcile:

```console
$ kubectl get tunnelinterface -n lab
NAME         DEVICE   TUNNEL   MODE         ADDRESS            OPER    IKE-SA   SYNCED   READY
r1-tunnel0   r1       0        ipsec-ipv4   192.168.100.1/24   ready   1/1      True     True
r3-tunnel0   r3       0        ipsec-ipv4   192.168.100.2/24   ready   1/1      True     True
```

See [Post-quantum IPsec on IOS XE](https://netclab.dev/netclab-xp/iosxe/).

### Installation

Needs the [prerequisites of netclab](https://github.com/netclab/netclab-chart#-prerequisites):
Docker, kind, kubectl, Helm, and uv. A kind cluster with Crossplane and the package:

```bash
CROSSPLANE=<release>   # a Crossplane v2 release
VERSION=<version>      # the newest iosxe/v* tag, without iosxe/

uvx netclab up --cluster xp --crossplane ${CROSSPLANE} \
  --configuration xpkg.upbound.io/netclab/configuration-iosxe:${VERSION}
```

The routers need RESTCONF and a user it accepts:
[Quick start](https://netclab.dev/netclab-xp/iosxe/#quick-start).

### Usage

Set each `Device`'s `address` to its router's RESTCONF address,
`iosxe/examples/device/r1.yaml` and `iosxe/scenarios/part9/r3/device.yaml`, then:

```bash
git clone https://github.com/netclab/netclab-xp
cd netclab-xp
kubectl apply -k iosxe/scenarios/prerequisites
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/part9 \
  | kubectl apply -f -
kubectl get device,tunnelinterface -n lab
```

Teardown and the rest: [Quick start](https://netclab.dev/netclab-xp/iosxe/#quick-start).

## Arista EOS

**One API for you, several mechanisms for the device.** Everything is a
Kubernetes resource, applied and reviewed the same way whatever the device
speaks. Underneath, RESTCONF carries structured data and reaches what OpenConfig
models, while eAPI carries CLI commands over JSON-RPC and reaches whatever the
CLI can say. They overlap heavily, and where they overlap, the mechanism is
selectable without changing the resource.

Above that, layers describing how much you configure at once:

```
Fabric (function-avd, installed apart)          a whole network, one design
   v
Router                                          one device, one resource
   v
BgpGlobal, BgpNeighbor, BgpPeerGroup,           one setting, one resource
RoutedInterface, LoopbackInterface,
IpRouting, EosCommand, ...
   v
provider-http                                   RESTCONF, JSON-RPC, eAPI
```

The low-level resources map closely onto what a device models; `Router`
composes them into something you would recognise as a router; and `Fabric`
describes the design of a whole network, leaving AVD to work out each switch's
configuration.

The bottom three layers are this package's own: twelve resource types in
`eos.netclab.dev`, installed together. `Fabric` is
[function-avd](https://github.com/netclab/function-avd)'s, and not installed
with configuration-eos.

### Scenarios

The repository carries runnable manifests for every mechanism, under
[`eos/scenarios/`](eos/scenarios/):

| scenario | mechanism |
|---|---|
| [`restconf`](eos/scenarios/restconf/) | OpenConfig over RESTCONF: the base config |
| [`jsonrpc`](eos/scenarios/jsonrpc/) | eAPI over JSON-RPC: settings OpenConfig does not model |
| [`eapi`](eos/scenarios/eapi/) | raw EOS CLI through `function-eapi` |
| [`router`](eos/scenarios/router/) | the `Router` abstraction |

`restconf`, `eapi` and `router` are alternatives to one another: each becomes
an owner of the same device configuration. See
[Scenarios](https://netclab.dev/netclab-xp/eos/scenarios/) for how to apply
and remove them.

## Contributing & extending

Contributions are welcome: new vendor-specific resource types, higher-level
abstractions, better compositions, examples, tests, or documentation.

## License

Licensed under the [Apache-2.0 License](LICENSE).
Copyright 2025 Michal Bakalarski and Netclab Contributors.
