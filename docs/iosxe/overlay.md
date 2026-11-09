# Overlay: static VTIs in VRFs

The usual shape of an IPsec overlay of static VTIs: the routers' WAN interfaces in a
front-door VRF, the tunnel in a VRF of its own. Here it is the tunnel of
[Part 9](part9.md), PPK included, with three fields more on its objects.

## The overlay

```
          VRF WAN                                               VRF WAN
r1 Gi2 10.0.12.1 ---- 10.0.12.2 Gi2 r2 Gi3 10.0.23.1 ---- 10.0.23.2 Gi2 r3
  VRF OVERLAY: Tunnel0 192.168.100.1  <== IKEv2 + PPK ==>  Tunnel0 192.168.100.2
```

| object | field | on the router |
|---|---|---|
| `Ikev2Policy` | `fvrf: WAN` | `match fvrf WAN` |
| `Ikev2Profile` | `fvrf: WAN` | `match fvrf WAN` |
| `TunnelInterface` | `fvrf: WAN` | `tunnel vrf WAN` |
| `TunnelInterface` | `vrf: OVERLAY` | `vrf forwarding OVERLAY` |

Without `fvrf` a policy and a profile match the global table alone, and the router's
`default` policy, which matches any VRF, takes no part once there is another policy: the
tunnel needs `match fvrf` in both. `fvrf: any` matches every VRF.

## Before

[Part 9](part9.md#before) as it stands, and on r1 and r3, by hand, both VRFs and
GigabitEthernet2 in WAN with a route in WAN to the other end. The package reads VRFs; it
does not make them. On r1:

```
configure terminal
vrf definition WAN
 address-family ipv4
 exit-address-family
 exit
vrf definition OVERLAY
 address-family ipv4
 exit-address-family
 exit
interface GigabitEthernet2
 vrf forwarding WAN
 ip address 10.0.12.1 255.255.255.0
 exit
ip route vrf WAN 10.0.23.0 255.255.255.0 10.0.12.2
end
```

On r3 the same, with `ip address 10.0.23.2 255.255.255.0` and
`ip route vrf WAN 10.0.12.0 255.255.255.0 10.0.23.1`. From r1:

```console
r1#ping vrf WAN 10.0.23.2
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 10.0.23.2, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/2 ms
```

## Apply

The scenario is part 9's, patched:

```yaml title="iosxe/scenarios/overlay/kustomization.yaml"
resources:
  - ../part9

patches:
  - target: {kind: Ikev2Policy}
    patch: '[{"op": "add", "path": "/spec/fvrf", "value": "WAN"}]'
  - target: {kind: Ikev2Profile}
    patch: '[{"op": "add", "path": "/spec/fvrf", "value": "WAN"}]'
  - target: {kind: TunnelInterface}
    patch: |-
      [{"op": "add", "path": "/spec/fvrf", "value": "WAN"},
       {"op": "add", "path": "/spec/vrf", "value": "OVERLAY"}]
```

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/overlay \
  | kubectl apply -f -
```

Each Device lists the router's VRFs:

```bash
kubectl get device -n lab -o custom-columns=NAME:.metadata.name,VRFS:.status.vrfs
```

```console
NAME   VRFS
r1     [OVERLAY WAN]
r3     [OVERLAY WAN]
```

An object naming a VRF its Device does not list applies nothing and is not Ready, and
`status.missingVrfs` names the VRF; once the router has it, the object goes on. The
objects come up in the order their `after` gives, the tunnel last:

```bash
kubectl wait --for=condition=Ready tunnelinterface --all -n lab --timeout=600s
kubectl get tunnelinterface -n lab
```

```console
tunnelinterface.iosxe.netclab.dev/r1--tunnel0--d311cfe5 condition met
tunnelinterface.iosxe.netclab.dev/r3--tunnel0--d311cfe5 condition met

NAME                    DEVICE   INTERFACE   TUNNEL-MODE   ADDRESS            MODE      OPER    IKE-SA   WANTS-NAME   SYNCED   READY   COMPOSITION                          AGE
r1--tunnel0--d311cfe5   r1       Tunnel0     ipsec-ipv4    192.168.100.1/24   Replace   ready   1/1                   True     True    tunnelinterfaces.iosxe.netclab.dev   4m23s
r3--tunnel0--d311cfe5   r3       Tunnel0     ipsec-ipv4    192.168.100.2/24   Replace   ready   1/1                   True     True    tunnelinterfaces.iosxe.netclab.dev   4m23s
```

## Both VRFs on the router

The IKEv2 SA runs in WAN and carries OVERLAY, on the PPK:

```console
r1#show crypto ikev2 sa
 IPv4 Crypto IKEv2  SA
Tunnel-id Local                 Remote                fvrf/ivrf            Status
3         10.0.12.1/500         10.0.23.2/500         WAN/OVERLAY          READY
      Encr: AES-CBC, keysize: 256, PRF: SHA512, Hash: SHA512, DH Grp:20, Auth sign: PSK, Auth verify: PSK, QR
      Life/Active Time: 86400/74 sec
      CE id: 0, Session-id: 7
      Local spi: 6A5F05130BA8D932       Remote spi: F16095FCCDC0E948
 IPv6 Crypto IKEv2  SA
r1#show crypto ikev2 sa detailed | include Quantum
      Quantum-safe Encryption using Manual PPK
```

Traffic in OVERLAY goes over the tunnel:

```console
r1#ping vrf OVERLAY 192.168.100.2
Type escape sequence to abort.
Sending 5, 100-byte ICMP Echos to 192.168.100.2, timeout is 2 seconds:
!!!!!
Success rate is 100 percent (5/5), round-trip min/avg/max = 1/24/114 ms
```

## Changing a VRF

`vrf`: the router takes the interface's address off with its VRF; the package's write
puts it back in the same transaction, and the tunnel's traffic moves to the new VRF.

`fvrf` from `any` to a VRF's name: the router refuses it in one write. Under `Replace`
it takes two pull requests, the first taking `fvrf` off, which the PUT removes from the
router:

```diff
 spec:
   managementPolicy: Replace
-  fvrf: any
```

and the second setting the name:

```diff
 spec:
   managementPolicy: Replace
+  fvrf: WAN
```

From a name to `any` is one pull request under `Replace`. Under `Merge` the router
refuses both directions, and a field taken out of the spec stays on the router, so the
change is made under `Replace`.

## Teardown

As [Part 9](part9.md#teardown), with the scenario's own path:

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/overlay \
  | kubectl delete -f -
```

The VRFs stay on the routers, as they were made: by hand. Back to part 9's routing, on r1,
the route first:

```
configure terminal
no ip route vrf WAN 10.0.23.0 255.255.255.0 10.0.12.2
interface GigabitEthernet2
 no vrf forwarding WAN
 ip address 10.0.12.1 255.255.255.0
 exit
no vrf definition OVERLAY
no vrf definition WAN
end
```

On r3 the same, with its address and route.
