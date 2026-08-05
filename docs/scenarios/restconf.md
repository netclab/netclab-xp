# RESTCONF — structured paths over OpenConfig

RESTCONF carries structured data: each resource becomes a PATCH against an
OpenConfig path on the device. What it reaches is what OpenConfig models — which
is most of a router's base configuration, and nothing beyond it.

This scenario builds that base on `ceos01`: a loopback and its address, an
address on Ethernet1, `ip routing`, and a BGP instance with a neighbour and a
peer group.

## Running it

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/restconf \
  | kubectl apply -f -
```

```bash
kubectl get netclab -n netclab
```

## What lands on the device

Seven manifests, one per setting, each naming the device it configures. This is
one of them:

```yaml
apiVersion: eos.netclab.dev/v1alpha1
kind: BgpGlobal
metadata:
  name: bgpglobal-on-ceos
spec:
  endpoint: ceos01.default.svc.cluster.local
  asn: 65001
  routerId: 10.0.0.1
  disableBgpDefaultIpv4Unicast: true
  maximumPaths:
    number: 4
    ecmp: 4
```

`kubectl get netclab` lists eight of them, not seven: a `BgpGlobal` with
`maximumPaths` composes a `BgpMultiPath`, and composed resources are resources
like any other.

Together they produce:

```console
router bgp 65001
   router-id 10.0.0.1
   no bgp default ipv4-unicast
   maximum-paths 4 ecmp 4
   neighbor EVPN-OVERLAY-PEERS peer group
   neighbor EVPN-OVERLAY-PEERS next-hop-unchanged
   neighbor EVPN-OVERLAY-PEERS update-source Loopback0
   neighbor EVPN-OVERLAY-PEERS bfd
   neighbor EVPN-OVERLAY-PEERS ebgp-multihop 3
   neighbor EVPN-OVERLAY-PEERS send-community
   neighbor EVPN-OVERLAY-PEERS maximum-routes 0
   neighbor 10.1.2.2 remote-as 65002
interface Loopback0
   ip address 10.0.0.1/32
```

The mapping stays close to one resource per config block: what you edit is the
device's own model.

## Teardown

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/restconf \
  | yq 'select(.kind != "Namespace")' \
  | kubectl delete -f -
```

All of it goes — the BGP instance, the loopback, `ip routing`, and the address
on Ethernet1, which is back to bare.
