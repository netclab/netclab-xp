# netclab-xp

> ***Extend Kubernetes to manage any resource anywhere***
> <br>Powered by [crossplane.io](https://www.crossplane.io)

**A Crossplane Configuration package for router configuration management.**

`netclab-xp` turns router configuration into Kubernetes resources — declarative,
versioned, reviewable, and reconciled like anything else in a cluster. It
targets devices that speak RESTCONF or JSON-RPC; Arista EOS is what it is built
and tested against today.

## 📖 Documentation

**[netclab.github.io/netclab-xp](https://netclab.github.io/netclab-xp/)**

| | |
|---|---|
| [Set up a lab](https://netclab.github.io/netclab-xp/lab/) | two cEOS devices on Kubernetes |
| [Install the package](https://netclab.github.io/netclab-xp/install/) | the Configuration, prerequisites, and the 0.2.x upgrade hazards |
| [Your first resource](https://netclab.github.io/netclab-xp/first-resource/) | one interface, then a BGP session between two devices |
| [Scenarios](https://netclab.github.io/netclab-xp/scenarios/) | every mechanism the package offers |

## What is in the package

Twelve resource types in the `eos.netclab.dev` API group, at two levels:

```
Router                                          one device, one resource
   ↓
BgpGlobal · BgpNeighbor · BgpPeerGroup ·        one setting, one resource
RoutedInterface · LoopbackInterface ·
IpRouting · EosCommand · …
   ↓
provider-http                                   RESTCONF · JSON-RPC · eAPI
```

The low-level resources map closely onto what a device models; `Router`
composes them into something you would recognise as a router.

A level above that, the [fabric scenario](https://netclab.github.io/netclab-xp/scenarios/fabric/)
configures a whole network from one AVD design. That API is not part of this
package — it ships in `configuration-avd`, pulled in as a dependency.

## Scenarios

The repository carries runnable manifests for every mechanism, under
[`scenarios/`](scenarios/):

| scenario | mechanism |
|---|---|
| [`restconf`](scenarios/restconf/) | OpenConfig over RESTCONF — the base config |
| [`jsonrpc`](scenarios/jsonrpc/) | eAPI over JSON-RPC — settings OpenConfig does not model |
| [`eapi`](scenarios/eapi/) | raw EOS CLI through `function-eapi` |
| [`router`](scenarios/router/) | the `Router` abstraction |
| [`fabric`](scenarios/fabric/) | an AVD model rendering a whole network |

`restconf`, `eapi` and `router` are alternatives to one another — each becomes
an owner of the same device configuration. See
[Scenarios](https://netclab.github.io/netclab-xp/scenarios/) for how to apply
and remove them.

## Contributing & extending

Contributions are welcome — new vendor-specific resource types, higher-level
abstractions, better compositions, examples, tests, or documentation.

## License

Licensed under the [Apache-2.0 License](LICENSE).
© 2025 Michal Bakalarski and Netclab Contributors.
