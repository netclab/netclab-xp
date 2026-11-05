# Part 9: a post-quantum preshared key

Part 9 of Cisco's IPsec series,
[Post-Quantum Key Exchange on Cisco Routers](https://blogs.cisco.com/developer/post-quantum-key-exchange-on-cisco-routers-ipsec-series-part-9),
builds an IKEv2 tunnel whose key exchange mixes in a post-quantum preshared key (PPK,
RFC 8784). Here the same exercise, with the same names, is a set of Kubernetes objects.

## The exercise

```
r1 Gi2 10.0.12.1 ---- 10.0.12.2 Gi2 r2 Gi3 10.0.23.1 ---- 10.0.23.2 Gi2 r3
      Tunnel0 192.168.100.1  <== IKEv2 + PPK ==>  Tunnel0 192.168.100.2
```

r2 only routes between r1 and r3. The names are the blog's: `CLASSICAL-PROPOSAL`,
`CLASSICAL-KEYRING`, `CLASSICAL-PROFILE` and the rest, and the PPK id `PPK-R1R3`.

## Before

The [Quick start](index.md#quick-start), steps 1 to 3, and the three routers cabled and
addressed as above, with r1 routing to 10.0.23.0/24 and r3 to 10.0.12.0/24 through r2.
RESTCONF on r1 and r3.

## Apply

Set each `Device`'s `address` to its router's RESTCONF address:
`iosxe/examples/device/r1.yaml` and `iosxe/scenarios/part9/r3/device.yaml`. Then:

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/part9 \
  | kubectl apply -f -
```

```console
<from the run>
```

Every object is in `FullControl`. The objects come up in the order their `after` gives,
the tunnel last:

```bash
kubectl wait --for=condition=Ready tunnelinterface --all -n lab --timeout=600s
kubectl get device,tunnelinterface -n lab
```

```console
<from the run>
```

The tunnel's state follows a provider poll, so `OPER` and `IKE-SA` lag the router by up to
a minute.

## The PPK

```console
r1#show crypto ikev2 sa detailed | include READY|Quantum
<from the run>
```

The router reports no PPK over RESTCONF, so the tunnel's object has no field for it; the
line above is the proof. The PPK and `keyring ppk` on the router:

```console
r1#show running-config | include ppk
<from the run>
```

## A change by hand is put back

On r1, a description and `shutdown` on Tunnel0, and group 19 in place of 20 in the
proposal:

```
configure terminal
interface Tunnel0
 description by hand
 shutdown
crypto ikev2 proposal CLASSICAL-PROPOSAL
 group 19
end
```

At the next poll both are put back, and each object records what it put back:

```bash
kubectl get tunnelinterface r1--tunnel0--d311cfe5 -n lab -o jsonpath='{.status.reverted}'
kubectl get ikev2proposal r1--classical-proposal--3a16aab3 -n lab -o jsonpath='{.status.reverted}'
```

```console
<from the run>
```

## Without the PPK

The same tunnel on the pre-shared key alone: the keyrings without `ppk`, the profiles
without `ppkKeyring`.

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/part9 \
  | yq 'del(select(.kind == "Ikev2Keyring") | .spec.peers[].ppk)
      | del(select(.kind == "Ikev2Profile") | .spec.ppkKeyring)' \
  | kubectl apply -f -
```

```console
r1#show crypto ikev2 sa detailed | include READY|Quantum
<from the run>
```

## Teardown

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/part9 \
  | kubectl delete -f -
```

```console
<from the run>
```

kubectl exits 1: for each object that another still names, the admission webhook
`nousages.protection.crossplane.io` denies the delete, and the Devices are named by every
object. Crossplane deletes those objects once nothing names them, the Devices last, and
the routers are clean when no Request is left:

```bash
kubectl get requests.http.m.crossplane.io -n lab
```

```console
<from the run>
```

Do not add `--cascade=foreground`: it waits on objects that are waiting on it.
