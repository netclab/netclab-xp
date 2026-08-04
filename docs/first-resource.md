# Your first resource

The [scenarios](scenarios/index.md) apply whole sets of manifests at once. This
page does the opposite: one resource at a time, by hand, so you can watch what
each one does to a device.

It assumes [devices](lab.md) and [the package](install.md) are in place.

```bash
kubectl create namespace netclab
```

## One interface

```bash
cat <<EOF | kubectl apply -f - -n netclab
apiVersion: eos.netclab.dev/v1alpha1
kind: RoutedInterface
metadata:
  name: r1e1ip
spec:
  endpoint: ceos01.default.svc.cluster.local
  ifName: Ethernet1
  ipv4Address: 10.10.10.1
  ipv4PrefixLength: 24
EOF
```

```bash
kubectl get netclab -n netclab
```

```console
NAME                                     ENDPOINT                           IF          IP           PLEN   SYNCED   READY
routedinterface.eos.netclab.dev/r1e1ip   ceos01.default.svc.cluster.local   Ethernet1   10.10.10.1   24     True     True
```

On the device:

```bash
kubectl exec ceos01 -- Cli -p15 -c "show run int Ethernet1"
```

```console
interface Ethernet1
   no switchport
   ip address 10.10.10.1/24
```

Removing the resource takes the configuration with it:

```bash
kubectl delete routedinterface r1e1ip -n netclab
```

## One router

`Router` composes the low-level resources — a BGP instance, a neighbor,
interfaces, a loopback, `ip routing` — from a single spec.

```bash
cat <<EOF | kubectl apply -f - -n netclab
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
  - neighborAsn: 65002
    neighborIp: 10.1.2.2
EOF
```

`kubectl get netclab -n netclab` now lists what that one resource produced: a
`BgpGlobal`, a `BgpNeighbor`, an `IpRouting`, a `LoopbackInterface` and two
`RoutedInterface`s, each named after the router and a hash of its inputs.

## Two routers, and a session that comes up

```bash
cat <<EOF | kubectl apply -f - -n netclab
apiVersion: eos.netclab.dev/v1alpha1
kind: Router
metadata:
  name: ceos02
spec:
  endpoint: ceos02.default.svc.cluster.local
  asn: 65002
  routerId: 10.0.0.2
  routedInterfaces:
  - ifName: Ethernet1
    ipv4Address: 10.1.2.2
    ipv4PrefixLength: 24
  bgpNeighbors:
  - neighborAsn: 65001
    neighborIp: 10.1.2.1
EOF
```

```bash
kubectl exec ceos01 -- Cli -p15 -c "show ip bgp summary"
```

```console
BGP summary information for VRF default
Router identifier 10.0.0.1, local AS number 65001
  Neighbor V AS           MsgRcvd   MsgSent  InQ OutQ  Up/Down State   PfxRcd
  10.1.2.2 4 65002              5         5    0    0 00:01:19 Estab   0
```

Two resources, two devices, and a protocol adjacency that actually came up.

## Clean up

```bash
kubectl delete netclab --all -n netclab
```

Watch the requests rather than the command — deletion returns long before the
devices change:

```bash
kubectl -n netclab get requests.http.m.crossplane.io -w
```
