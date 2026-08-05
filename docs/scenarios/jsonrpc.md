# JSON-RPC — what OpenConfig does not model

Spanning-tree mode, the internal VLAN range, BGP multipath, redistributing a
loopback into BGP: ordinary settings that OpenConfig does not model, so no
OpenConfig path reaches them.

This scenario configures them on `ceos01` over eAPI's JSON-RPC endpoint —
commands, but sent as resources like everything else here.

## Running it

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/jsonrpc \
  | kubectl apply -f -
```

## What lands on the device

Five manifests: a `StpMode`, a `VlanInternalAllocation`, a `BgpMultiPath`, a
`BgpInterfaceExport` — and a `BgpGlobal` asking for this mechanism by label:

```yaml
apiVersion: eos.netclab.dev/v1alpha1
kind: BgpGlobal
metadata:
  name: bgpglobal-on-ceos-jsonrpc
spec:
  crossplane:
    compositionSelector:
      matchLabels:
        eos.netclab.dev/mechanism: jsonrpc
  endpoint: ceos01.default.svc.cluster.local
  asn: 65001
  routerId: 10.0.0.1
```

Omit the selector and that manifest goes over RESTCONF instead. Changing
mechanism is a label, not a different resource.

Together they produce:

```console
route-map RM-Loopback0-2-BGP permit 10
   match ip address prefix-list PL-Loopback0
router bgp 65001
   router-id 10.0.0.1
   maximum-paths 4 ecmp 4
   redistribute connected route-map RM-Loopback0-2-BGP
vlan internal order ascending range 1006 1199
spanning-tree mode none
```

Three of those lines came from one resource: exporting a loopback into BGP means
a prefix-list, a route-map matching it, and a `redistribute` naming that
route-map. You asked for the export.

## Teardown

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/jsonrpc \
  | yq 'select(.kind != "Namespace")' \
  | kubectl delete -f -
```

`show run section bgp` comes back empty and `spanning-tree mode` returns to
`mstp`. The whole BGP instance goes, not just the settings inside it — which is
why `BgpGlobal` is part of this scenario at all. Entering a configuration
section on EOS creates it, so resources that only edit *inside* `router bgp`
would leave an empty instance behind. Something has to own the section.
