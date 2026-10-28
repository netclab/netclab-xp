# netclab-xp

> ***Extend Kubernetes to manage any resource anywhere***
> <br>Powered by [crossplane.io](https://www.crossplane.io)

**A Crossplane Configuration package for router configuration management.**

`netclab-xp` turns router configuration into Kubernetes resources — declarative,
versioned, reviewable, and reconciled like anything else in a cluster. It
targets devices that speak RESTCONF or JSON-RPC; Arista EOS is what it is built
and tested against today.

## 📖 Documentation

**[netclab.dev/netclab-xp](https://netclab.dev/netclab-xp/)**

| | |
|---|---|
| [Set up a lab](https://netclab.dev/netclab-xp/eos/lab/) | two cEOS devices on Kubernetes |
| [Install the package](https://netclab.dev/netclab-xp/eos/install/) | the Configuration and its prerequisites |
| [Your first resource](https://netclab.dev/netclab-xp/eos/first-resource/) | one interface, then a BGP session between two devices |
| [Scenarios](https://netclab.dev/netclab-xp/eos/scenarios/) | every mechanism the package offers |

## What you get

**One API for you, several mechanisms for the device.** Everything is a
Kubernetes resource, applied and reviewed the same way whatever the device
speaks. Underneath, RESTCONF carries structured data and reaches what OpenConfig
models, while eAPI carries CLI commands over JSON-RPC and reaches whatever the
CLI can say. They overlap heavily — and where they overlap, the mechanism is
selectable without changing the resource.

Above that, layers describing how much you configure at once:

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

The low-level resources map closely onto what a device models; `Router`
composes them into something you would recognise as a router; and `Fabric`
describes the design of a whole network, leaving AVD to work out each switch's
configuration.

The bottom three layers are this package's own — twelve resource types in
`eos.netclab.dev`, installed together. `Fabric` is
[function-avd](https://github.com/netclab/function-avd)'s, and not installed
with netclab-xp.

## Scenarios

The repository carries runnable manifests for every mechanism, under
[`eos/scenarios/`](eos/scenarios/):

| scenario | mechanism |
|---|---|
| [`restconf`](eos/scenarios/restconf/) | OpenConfig over RESTCONF — the base config |
| [`jsonrpc`](eos/scenarios/jsonrpc/) | eAPI over JSON-RPC — settings OpenConfig does not model |
| [`eapi`](eos/scenarios/eapi/) | raw EOS CLI through `function-eapi` |
| [`router`](eos/scenarios/router/) | the `Router` abstraction |

`restconf`, `eapi` and `router` are alternatives to one another — each becomes
an owner of the same device configuration. See
[Scenarios](https://netclab.dev/netclab-xp/eos/scenarios/) for how to apply
and remove them.

## Contributing & extending

Contributions are welcome — new vendor-specific resource types, higher-level
abstractions, better compositions, examples, tests, or documentation.

## License

Licensed under the [Apache-2.0 License](LICENSE).
© 2025 Michal Bakalarski and Netclab Contributors.
