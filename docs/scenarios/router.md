# Router — one device, one resource

`Router` describes the device — its ASN, router-id, routed interfaces and BGP
neighbours — instead of configuring it setting by setting, and composes the
per-setting resources itself.

A `Router` owns everything it composes — a `BgpGlobal`, a `BgpNeighbor`, an
`IpRouting`, a `LoopbackInterface` and the `RoutedInterface`s — so one manifest
describes one device. This scenario uses both lab devices.

## Running it

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/router \
  | kubectl apply -f -
```

## What lands on the devices

Two manifests, one per device:

```yaml
apiVersion: eos.netclab.dev/v1alpha1
kind: Router
metadata:
  name: ceos01
spec:
  endpoint: ceos01.default.svc.cluster.local
  asn: 65001
  routerId: 10.0.0.1
  routedInterfaces:
  - ifName: Ethernet1
    ipv4Address: 10.1.2.1
    ipv4PrefixLength: 24
  bgpNeighbors:
  - networkInstance: default
    neighborAsn: 65002
    neighborIp: 10.1.2.2
```

Each one fans out into six resources, named after the router and a hash of what
produced them:

```console
bgpglobal.eos.netclab.dev/ceos01-bd6e6aeb539a
bgpneighbor.eos.netclab.dev/ceos01-c4d4c8b69801
iprouting.eos.netclab.dev/ceos01-722bc966d21d
loopbackinterface.eos.netclab.dev/ceos01-d7e59e7679cd
routedinterface.eos.netclab.dev/ceos01-6141af156de9   # Loopback0, 10.0.0.1/32
routedinterface.eos.netclab.dev/ceos01-c6d45d06911b   # Ethernet1, 10.1.2.1/24
```

The loopback is the part you did not write: `routerId` implies an address, and
the composition creates the interface to hold it.

Two devices configured this way have a working eBGP session between them:

```bash
kubectl exec ceos01 -- Cli -p15 -c "show ip bgp summary"
```

```console
BGP summary information for VRF default
Router identifier 10.0.0.1, local AS number 65001
Neighbor Status Codes: m - Under maintenance
  Neighbor V AS           MsgRcvd   MsgSent  InQ OutQ  Up/Down State   PfxRcd PfxAcc PfxAdv
  10.1.2.2 4 65002              4         4    0    0 00:00:10 Estab   0      0      0
```

Two resources, two devices, and an adjacency that came up rather than
configuration that merely matched.

## Teardown

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/router \
  | yq 'select(.kind != "Namespace")' \
  | kubectl delete -f -
```

Both devices come back to bare: no BGP instance, no loopback, Ethernet1
unconfigured.
