# netclab-xp

> ***Extend Kubernetes to manage any resource anywhere***
> <br>Powered by [crossplane.io](https://www.crossplane.io)

**Crossplane Configuration Package for Router Configuration Management**

`netclab-xp` enables declarative, GitOps-driven lifecycle management of physical, virtualized, and containerized routers using Crossplane.
It provides a layered abstractions, allowing network teams to manage router configuration consistently and reproducibly.

---

## Overview

`netclab-xp` is organized around a set of **layered abstractions**, for example:

```
FabricIP / Evpn
     ↓
Router (eos)
     ↓
Loopback / RoutedInterface / BgpGlobal / BgpNeighbor
     ↓
provider-http (RESTCONF, JSON-RPC)
```

* **High-Level Services:** Vendor-neutral abstractions such as `FabricIP` and `EvpnService`.
* **Mid-Level Abstractions:** Router constructs composed from multiple low-level XRDs (`Router`).
* **Low-Level XRDs:** Vendor-specific resources directly representing YANG models or configuration components (e.g., `RoutedInterface`, `BgpNeighbor`).
* **Lowest Layer:** Raw RESTCONF or JSON-RPC operations via `provider-http`.

This model hides vendor-specific complexity while enabling reusable, declarative network configuration.

---

## Benefits

* **Declarative operations** — manage network configuration as Kubernetes resources
* **GitOps-native** — versioned, reviewable router configuration
* **Vendor-neutral abstractions** — consistent workflows across platforms
* **Encapsulated complexity** — device-specific modeling hidden behind compositions
* **Composable and reusable** — easily onboard new routers and services

---

## Supported Devices

* **RESTCONF- or JSON-RPC-enabled routers**
  *Currently supported:* Arista EOS

* **Other vendors**
  Not yet supported. Additional capabilities may be added via new providers or JSON-RPC through `provider-http` if applicable.

---

## Getting Started

### Requirements

* Target routers
  (provided here via [`netclab-chart`](https://github.com/netclab/netclab-chart))
* A Kubernetes cluster with Crossplane installed
  (in this setup, the same cluster that runs the netclab-chart topology)
* The `netclab-xp` configuration package, which includes all required Crossplane dependencies.

### Installation Steps

#### 1. Install [`netclab-chart`](https://github.com/netclab/netclab-chart)

Make sure you have downloaded the cEOS image from Arista Networks and imported it into your cluster.


#### 2. Install Crossplane

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace
```

#### 3. Install the netclab-xp Configuration Package

```bash
cat <<EOF | kubectl apply -f -
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: netclab-xp
spec:
  package: xpkg.upbound.io/netclab/netclab-xp:v0.2.12
EOF
```

#### 4. Add ProviderConfig, EnvironmentConfig and Secret

```bash
cat <<EOF | kubectl apply -f -
apiVersion: http.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: None
---
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: endpoint-protocols
data:
  restconf:
    scheme: https
    port: 6020
  jsonrpc:
    scheme: http
    port: 6021
---
apiVersion: v1
kind: Secret
metadata:
  name: eos-creds
  namespace: crossplane-system
type: Opaque
data:
  basicAuth: YXJpc3RhOmFyaXN0YQ==
EOF
```

---

## Example Usage

### Start netclab-chart topology with two cEOS routers

> You may observe retrying pods for jobs generating certificates on cEOS.
> This is expected — booting cEOS takes time.

```bash
cat << EOF | helm install ceos netclab/netclab --values -
topology:
  networks:
  - name: b1
  - name: b2
    type: bridge
  - name: b3
    type: bridge
  nodes:
  - name: ceos01
    type: ceos
    memory: 2Gi
    cpu: 1000m
    interfaces:
    - name: eth1
      network: b1
    - name: eth2
      network: b2
  - name: ceos02
    type: ceos
    memory: 2Gi
    cpu: 1000m
    interfaces:
    - name: eth1
      network: b1
    - name: eth2
      network: b3
  - name: h01
    type: linux
    interfaces:
    - name: e1
      network: b2
  - name: h02
    type: linux
    interfaces:
    - name: e1
      network: b3
EOF
```

### Check topology

```bash
kubectl get pod
```

Example:

```
NAME                         READY   STATUS      RESTARTS   AGE
ceos01                       1/1     Running     0          2m
ceos01-generate-cert-r7kml   0/1     Completed   4          2m
ceos02                       1/1     Running     0          2m
ceos02-generate-cert-nxfp4   0/1     Completed   4          2m
```

---

## RoutedInterface

### Apply interface configuration on ceos01:

```bash
cat <<EOF | kubectl apply -f -
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

### Check resource:

```bash
kubectl get netclab
```

Example output:

```bash
NAME                                     ENDPOINT                           IF          IP           PLEN   SYNCED   READY   COMPOSITION                        AGE
routedinterface.eos.netclab.dev/r1e1ip   ceos01.default.svc.cluster.local   Ethernet1   10.10.10.1   24     True     True    routedinterfaces.eos.netclab.dev   8s
```

### Check device configuration:

```bash
kubectl exec ceos01 -- Cli -p15 -c "show run int Ethernet1"
```

```console
interface Ethernet1
   no switchport
   ip address 10.10.10.1/24
```

### Remove configuration

```bash
kubectl delete routedinterface r1e1ip
```

---

## Routers (eos)

### Apply configuration on ceos01:

```bash
cat <<EOF | kubectl apply -f -
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

### Check resource:

```bash
kubectl get router ceos01
```

Example output:

```bash
NAME     ENDPOINT                           ASN     ROUTER-ID   SYNCED   READY   COMPOSITION               AGE
ceos01   ceos01.default.svc.cluster.local   65001   10.0.0.1    True     True    routers.eos.netclab.dev   62s
```

### Verify all SYNCED and READY:

```bash
kubectl get netclab
```

Example output:

```bash
NAME                                            ENDPOINT                           ASN     ROUTER-ID   SYNCED   READY   COMPOSITION                  AGE
bgpglobal.eos.netclab.dev/ceos01-abcf5d7dbd2a   ceos01.default.svc.cluster.local   65001   10.0.0.1    True     True    bgpglobals.eos.netclab.dev   82s

NAME                                              ENDPOINT                           VRF       REMOTE-AS   REMOTE-IP   SYNCED   READY   COMPOSITION                    AGE
bgpneighbor.eos.netclab.dev/ceos01-973c82346f34   ceos01.default.svc.cluster.local   default   65002       10.1.2.2    True     True    bgpneighbors.eos.netclab.dev   82s

NAME                                            ENDPOINT                           SYNCED   READY   COMPOSITION                  AGE
iprouting.eos.netclab.dev/ceos01-5525df60016e   ceos01.default.svc.cluster.local   True     True    iproutings.eos.netclab.dev   82s

NAME                                                    ENDPOINT                           IF          SYNCED   READY   COMPOSITION                          AGE
loopbackinterface.eos.netclab.dev/ceos01-f7043813344c   ceos01.default.svc.cluster.local   Loopback0   True     True    loopbackinterfaces.eos.netclab.dev   82s

NAME                                                  ENDPOINT                           IF          IP         PLEN   SYNCED   READY   COMPOSITION                        AGE
routedinterface.eos.netclab.dev/ceos01-466930a040e3   ceos01.default.svc.cluster.local   Loopback0   10.0.0.1   32     True     True    routedinterfaces.eos.netclab.dev   82s
routedinterface.eos.netclab.dev/ceos01-ce9e542ce06c   ceos01.default.svc.cluster.local   Ethernet1   10.1.2.1   24     True     True    routedinterfaces.eos.netclab.dev   82s

NAME                            ENDPOINT                           ASN     ROUTER-ID   SYNCED   READY   COMPOSITION               AGE
router.eos.netclab.dev/ceos01   ceos01.default.svc.cluster.local   65001   10.0.0.1    True     True    routers.eos.netclab.dev   82s
```

### Add ceos02:

```bash
cat <<EOF | kubectl apply -f -
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

### Check resources:

```bash
kubectl get routers
```

Example output:

```bash
NAME     ENDPOINT                           ASN     ROUTER-ID   SYNCED   READY   COMPOSITION               AGE
ceos01   ceos01.default.svc.cluster.local   65001   10.0.0.1    True     True    routers.eos.netclab.dev   3m36s
ceos02   ceos02.default.svc.cluster.local   65002   10.0.0.2    True     True    routers.eos.netclab.dev   59s
```

### Check BGP on the router:

```bash
kubectl exec ceos01 -- Cli -p15 -c "show ip bgp summary"
```

```console
BGP summary information for VRF default
Router identifier 10.0.0.1, local AS number 65001
Neighbor Status Codes: m - Under maintenance
  Neighbor V AS           MsgRcvd   MsgSent  InQ OutQ  Up/Down State   PfxRcd PfxAcc PfxAdv
  10.1.2.2 4 65002              5         5    0    0 00:01:19 Estab   0      0      0
```

### Remove all configuration:

```bash
kubectl delete netclab --all
```

```bash
helm uninstall ceos
```

---

## Contributing & Extending

`netclab-xp` is designed to be extensible, and contributions are encouraged.
You can help improve or extend the project by:

* Adding new vendor-specific XRDs
* Creating high-level network abstractions (e.g., EVPN, fabric services)
* Enhancing router compositions
* Contributing examples, tests, or documentation improvements
* Fixing issues or proposing enhancements via pull requests

---

## License

Licensed under the [Apache-2.0 License](LICENSE).
© 2025 Michal Bakalarski and Netclab Contributors.

---
