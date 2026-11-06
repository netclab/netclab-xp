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
<from the run>
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
<from the run>
```

An object naming a VRF its Device does not list applies nothing and is not Ready, and
`status.missingVrfs` names the VRF; once the router has it, the object goes on. The
objects come up in the order their `after` gives, the tunnel last:

```bash
kubectl wait --for=condition=Ready tunnelinterface --all -n lab --timeout=600s
kubectl get tunnelinterface -n lab
```

```console
<from the run>
```

## Both VRFs on the router

The IKEv2 SA runs in WAN and carries OVERLAY, on the PPK:

```console
r1#show crypto ikev2 sa
<from the run>
r1#show crypto ikev2 sa detailed | include Quantum
<from the run>
```

Traffic in OVERLAY goes over the tunnel:

```console
r1#ping vrf OVERLAY 192.168.100.2
<from the run>
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
