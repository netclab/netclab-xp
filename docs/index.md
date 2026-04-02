---
marp: true
theme: default
author: Michal Bakalarski
title: netclab-xp
keywords: kubernetes,crossplane,networkautomation,cloudNative,yang,arista,restconf,infrastructure,controlplane,openconfig,json-rpc,iac,devops,gitops,netdevops,netclab,netclab-xp
paginate: true
backgroundColor: '#1E293B'  # dark slate
color: '#F8FAFC'            # light text
---

# 🚀 Introducing [**netclab-xp**](https://github.com/netclab/netclab-xp)
*Declarative Router Configuration with Crossplane*  
<br>
> ***Extend Kubernetes to manage any resource anywhere***
> Powered by [crossplane.io](https://www.crossplane.io)

---

# 🔧 Why netclab-xp Matters
<br>

- **Declarative & GitOps-ready** → manage routers like cloud resources  
- **Kubernetes-native state** → continuous reconciliation  
- **OpenConfig** → differences handled automatically  
- **RESTCONF and JSON-RPC support** → starting with Arista EOS / cEOS  
- **Fast onboarding** → add new routers or services easily

---

# ⚙️ Abstractions
<br>

***High-Level Services*** <span style="color:#60A5FA">`FabricIP` / `EvpnService`</span>  
      ▼  
***Mid-Level Router Abstractions*** <span style="color:#60A5FA">`Router`</span>  
      ▼  
***Low-Level XRDs*** <span style="color:#60A5FA">`Loopback` / `RoutedInterface` / `BgpGlobal` / `BgpNeighbor`</span>  
      ▼  
***RESTCONF & JSON-RPC Provider*** <span style="color:#60A5FA">`provider-http`</span>

---

# RoutedInterface

---

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

---

# Check device

```bash
kubectl exec -ti ceos01 -- Cli
```

```console
ceos01>en
ceos01#show run int Ethernet1
interface Ethernet1
   no switchport
   ip address 10.10.10.1/24
```

---

# Two routers with BGP

---

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

---

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

---

# Check resources

```bash
kubectl get routers
```

```bash
NAME     ENDPOINT                           ASN     ROUTER-ID   SYNCED   READY   COMPOSITION               AGE
ceos01   ceos01.default.svc.cluster.local   65001   10.0.0.1    True     True    routers.eos.netclab.dev   3m36s
ceos02   ceos02.default.svc.cluster.local   65002   10.0.0.2    True     True    routers.eos.netclab.dev   59s
```

---

# Check BGP on ceos01

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

---

# Verify more SYNCED and READY

```bash
kubectl get netclab
```

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

---

# 🎯 Next Steps

*Repo:*
[https://github.com/netclab/netclab-xp](https://github.com/netclab/netclab-xp)

*Registry:*
[https://marketplace.upbound.io/configurations/netclab/netclab-xp](https://marketplace.upbound.io/configurations/netclab/netclab-xp)

*Listed in Crossplane Adopters:*
curl -s https://github.com/crossplane/crossplane/blob/main/ADOPTERS.md | grep -o -E 'github.com/[a-z]+/netclab-xp'
