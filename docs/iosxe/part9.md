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
device.iosxe.netclab.dev/r1 created
device.iosxe.netclab.dev/r3 created
ikev2keyring.iosxe.netclab.dev/r1--classical-keyring--eb60cb7d created
ikev2keyring.iosxe.netclab.dev/r3--classical-keyring--eb60cb7d created
ikev2policy.iosxe.netclab.dev/r1--classical-policy--17d97755 created
ikev2policy.iosxe.netclab.dev/r3--classical-policy--17d97755 created
ikev2profile.iosxe.netclab.dev/r1--classical-profile--cdf1f733 created
ikev2profile.iosxe.netclab.dev/r3--classical-profile--cdf1f733 created
ikev2proposal.iosxe.netclab.dev/r1--classical-proposal--3a16aab3 created
ikev2proposal.iosxe.netclab.dev/r3--classical-proposal--3a16aab3 created
ipsecprofile.iosxe.netclab.dev/r1--classical-ipsec--461c477a created
ipsecprofile.iosxe.netclab.dev/r3--classical-ipsec--461c477a created
ipsectransformset.iosxe.netclab.dev/r1--classical-ts--771f3cb2 created
ipsectransformset.iosxe.netclab.dev/r3--classical-ts--771f3cb2 created
tunnelinterface.iosxe.netclab.dev/r1--tunnel0--d311cfe5 created
tunnelinterface.iosxe.netclab.dev/r3--tunnel0--d311cfe5 created
```

Every object is in `Replace`. The objects come up in the order their `after` gives,
the tunnel last:

```bash
kubectl wait --for=condition=Ready tunnelinterface --all -n lab --timeout=600s
kubectl get device,tunnelinterface -n lab
```

```console
tunnelinterface.iosxe.netclab.dev/r1--tunnel0--d311cfe5 condition met
tunnelinterface.iosxe.netclab.dev/r3--tunnel0--d311cfe5 condition met

NAME                          ADDRESS        SYNCED   READY   COMPOSITION                 AGE
device.iosxe.netclab.dev/r1   172.18.0.101   True     True    devices.iosxe.netclab.dev   3m34s
device.iosxe.netclab.dev/r3   172.18.0.103   True     True    devices.iosxe.netclab.dev   3m34s

NAME                                                      DEVICE   INTERFACE   TUNNEL-MODE   ADDRESS            MODE      OPER    IKE-SA   WANTS-NAME   SYNCED   READY   COMPOSITION                          AGE
tunnelinterface.iosxe.netclab.dev/r1--tunnel0--d311cfe5   r1       Tunnel0     ipsec-ipv4    192.168.100.1/24   Replace   ready   1/1                   True     True    tunnelinterfaces.iosxe.netclab.dev   3m34s
tunnelinterface.iosxe.netclab.dev/r3--tunnel0--d311cfe5   r3       Tunnel0     ipsec-ipv4    192.168.100.2/24   Replace   ready   1/1                   True     True    tunnelinterfaces.iosxe.netclab.dev   3m34s
```

The tunnel's state follows a provider poll, so `OPER` and `IKE-SA` lag the router by up to
a minute.

## The PPK

```console
r1#show crypto ikev2 sa detailed | include READY|Quantum
2         10.0.12.1/500         10.0.23.2/500         none/none            READY
      Quantum-safe Encryption using Manual PPK
```

The router reports no PPK over RESTCONF, so the tunnel's object has no field for it; the
line above is the proof. The PPK and `keyring ppk` on the router:

```console
r1#show running-config | include ppk
  ppk manual id PPK-R1R3 key hex 48656C6C6F506F737451756172746E756D Required
 keyring ppk CLASSICAL-KEYRING
event manager environment netclab-0fb93954 "5af41a49 Ikev2Keyring/CLASSICAL-KEYRING/R3/ppk"
event manager environment netclab-96580d81 "eb60cb7d Ikev2Profile/CLASSICAL-PROFILE/ppk CLASSICAL-KEYRING"
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
{"drift":[],"extra":[{"device":["\"by hand\""],"field":"description"},{"device":["[null]"],"field":"shutdown"}],"time":"2026-11-09T10:16:24Z"}
{"drift":[{"device":["19"],"field":"group","spec":["20"]}],"extra":[{"device":["19"],"field":"group"}],"time":"2026-11-09T10:16:04Z"}
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
1         10.0.12.1/500         10.0.23.2/500         none/none            READY
```

## Teardown

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/part9 \
  | kubectl delete -f -
```

```console
ikev2policy.iosxe.netclab.dev "r1--classical-policy--17d97755" deleted from lab namespace
ikev2policy.iosxe.netclab.dev "r3--classical-policy--17d97755" deleted from lab namespace
ikev2proposal.iosxe.netclab.dev "r1--classical-proposal--3a16aab3" deleted from lab namespace
tunnelinterface.iosxe.netclab.dev "r1--tunnel0--d311cfe5" deleted from lab namespace
tunnelinterface.iosxe.netclab.dev "r3--tunnel0--d311cfe5" deleted from lab namespace
Error from server (This resource is in-use by 7 usage(s), including the *v1beta1.Usage "r1--tunnel0--d311cfe5-18442af96999" (in namespace "lab") by resource TunnelInterface/r1--tunnel0--d311cfe5.): error when deleting "STDIN": admission webhook "nousages.protection.crossplane.io" denied the request: This resource is in-use by 7 usage(s), including the *v1beta1.Usage "r1--tunnel0--d311cfe5-18442af96999" (in namespace "lab") by resource TunnelInterface/r1--tunnel0--d311cfe5.
...
```

kubectl exits 1: for each object that another still names, the admission webhook
`nousages.protection.crossplane.io` denies the delete, and the Devices are named by every
object. Crossplane deletes those objects once nothing names them, the Devices last, and
the routers are clean when no Request is left:

```bash
kubectl get requests.http.m.crossplane.io -n lab
```

```console
No resources found in lab namespace.
```

Do not add `--cascade=foreground`: it waits on objects that are waiting on it.
