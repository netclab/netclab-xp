# Post-quantum IPsec on IOS XE

`configuration-iosxe` configures Cisco IOS XE over RESTCONF. Its first use is part 9 of
Cisco's IPsec series,
[Post-Quantum Key Exchange on Cisco Routers](https://blogs.cisco.com/developer/post-quantum-key-exchange-on-cisco-routers-ipsec-series-part-9):
an IKEv2 tunnel whose key exchange mixes in a post-quantum preshared key (PPK, RFC 8784).
Here the same exercise, with the same names, is a set of Kubernetes objects kept on the
routers by reconcile.

```console
$ kubectl get tunnelinterface -n lab
NAME         DEVICE   TUNNEL   MODE         ADDRESS            OPER    IKE-SA   SYNCED   READY
r1-tunnel0   r1       0        ipsec-ipv4   192.168.100.1/24   ready   1/1      True     True
r3-tunnel0   r3       0        ipsec-ipv4   192.168.100.2/24   ready   1/1      True     True
```

```console
r1#show crypto ikev2 sa detailed | include READY|Quantum
1         10.0.12.1/500         10.0.23.2/500         none/none            READY
      Quantum-safe Encryption using Manual PPK
```

## The exercise

```
r1 Gi2 10.0.12.1 ---- 10.0.12.2 Gi2 r2 Gi3 10.0.23.1 ---- 10.0.23.2 Gi2 r3
      Tunnel0 192.168.100.1  <== IKEv2 + PPK ==>  Tunnel0 192.168.100.2
```

r2 only routes between r1 and r3. The names are the blog's: `CLASSICAL-PROPOSAL`,
`CLASSICAL-KEYRING`, `CLASSICAL-PROFILE` and the rest, and the PPK id `PPK-R1R3`.

## One object per router setting

| kind | on the router |
|---|---|
| `Device` | the router's RESTCONF address and credentials |
| `Ikev2Proposal` | `crypto ikev2 proposal` |
| `Ikev2Policy` | `crypto ikev2 policy` |
| `Ikev2Keyring` | `crypto ikev2 keyring`, with `ppk manual` per peer |
| `Ikev2Profile` | `crypto ikev2 profile`, with `keyring ppk` |
| `IpsecTransformSet` | `crypto ipsec transform-set` |
| `IpsecProfile` | `crypto ipsec profile` |
| `TunnelInterface` | `interface Tunnel` |

The keyring of r1, with the PPK it shares with r3:

```yaml
apiVersion: iosxe.netclab.dev/v1alpha1
kind: Ikev2Keyring
metadata:
  name: r1-ikev2-keyring
spec:
  deviceRef:
    name: r1
  name: CLASSICAL-KEYRING
  peers:
  - name: R3
    address: 10.0.23.2
    preSharedKeySecretRef:
      name: ike-keys
      key: psk
    ppk:
      id: PPK-R1R3
      keySecretRef:
        name: ike-keys
        key: ppk-hex
```

## What it does

The configuration is kept, not pushed: a change made by hand is put back, and the
tunnel's state is read back into its object rather than into a report of one run.

- Applied at once, in any order: each object waits until the ones it names are Ready.
- The objects name a Secret for the PSK and the PPK, so they can go to Git without the keys.
- A new PPK goes with a new id, and the SA is renegotiated on it.
- What the objects configure is put back within a minute after a change by hand: a
  `shutdown` or a description on Tunnel0, for one.
- The tunnel's object shows its interface state, and its IKEv2 SA with the other router:
  `active`, `pending` or `none`.
- Deleting the objects removes everything they configured; each router is left with its
  underlay.

## Limits

- PPK, not ML-KEM. The Catalyst 8000V answers `IKEv2 PQC is not supported on this
  platform`: ML-KEM needs a Secure Router, C8100 to C8500. Part 12 of the series
  [automates it](https://github.com/juliogomez/pqc) over NETCONF, on the same YANG.
- Tested on Catalyst 8000V 17.18.02. The PPK lines go over `Cisco-IOS-XE-cli-rpc`, since
  the YANG of 17.18 has none.
- The tunnel's state has no PPK field: the router reports none over RESTCONF. The proof
  is `show crypto ikev2 sa detailed` above.

## Quick start

### 1. The routers

Three routers on IOS XE 17.18, cabled and addressed as above, with r1 routing to
10.0.23.0/24 and r3 to 10.0.12.0/24 through r2, and licensed for IPsec. On r1 and r3,
RESTCONF and a user it accepts:

```
username cisco privilege 15 secret cisco
ip http secure-server
ip http authentication local
restconf
```

RESTCONF answers:

```bash
curl -sk -u cisco:cisco -H 'Accept: application/yang-data+json' \
  https://<r1>/restconf/data/Cisco-IOS-XE-native:native/hostname
```

### 2. The cluster and the package

A kind cluster with Crossplane and the package, in one command. `netclab up` needs the
[prerequisites of netclab](https://github.com/netclab/netclab-chart#-prerequisites):
Docker, kind, kubectl, Helm, and uv for `uvx`. The cluster has to reach the routers'
RESTCONF addresses.

```bash
CROSSPLANE=<release>   # a Crossplane v2 release
VERSION=<version>      # the newest iosxe/v* tag, without iosxe/

uvx netclab up --cluster xp --crossplane ${CROSSPLANE} \
  --configuration xpkg.upbound.io/netclab/configuration-iosxe:${VERSION}
```

The versions are the [tags](https://github.com/netclab/netclab-xp/tags) named `iosxe/v*`.
In a cluster that already runs Crossplane, apply the Configuration as in
[Install the package](../eos/install.md#the-configuration), with `configuration-iosxe` in
place of `configuration-eos`.

### 3. The prerequisites

From a clone of the repository:

```bash
git clone https://github.com/netclab/netclab-xp
cd netclab-xp

kubectl apply -k iosxe/scenarios/prerequisites
```

The namespace `lab`, the ClusterProviderConfig, and two Secrets: the routers' credentials
and the keys of part 9. The values are the lab's; change them in
`iosxe/scenarios/prerequisites/secrets.yaml` for your routers.

### 4. Part 9

Set each `Device`'s `address` to its router's RESTCONF address:
`iosxe/examples/device/r1.yaml` and `iosxe/scenarios/part9/r3/device.yaml`. Then:

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/part9 \
  | kubectl apply -f -
kubectl get device,tunnelinterface -n lab
```

The tunnels come up once every object is Ready. Their state follows a provider poll, so
`OPER` and `IKE-SA` lag the router by up to a minute.

### 5. Teardown

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone iosxe/scenarios/part9 \
  | kubectl delete -f -
```

kubectl exits 1: for each object that another still names, the admission webhook
`nousages.protection.crossplane.io` denies the delete. Crossplane deletes those objects
once nothing names them, one layer after another, and the routers are clean when no
Request is left:

```bash
kubectl get requests.http.m.crossplane.io -n lab
```

Do not add `--cascade=foreground`: it waits on objects that are waiting on it.
