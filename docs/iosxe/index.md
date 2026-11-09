# IPsec on IOS XE

`configuration-iosxe` configures IPsec on Cisco IOS XE over RESTCONF: each section of the
router's configuration is a Kubernetes object, kept on the router by reconcile. Its first
use is part 9 of Cisco's IPsec series,
[Post-Quantum Key Exchange on Cisco Routers](https://blogs.cisco.com/developer/post-quantum-key-exchange-on-cisco-routers-ipsec-series-part-9),
in [Part 9](part9.md):

```console
$ kubectl get tunnelinterface -n lab
NAME                    DEVICE   INTERFACE   TUNNEL-MODE   ADDRESS            MODE      OPER    IKE-SA   WANTS-NAME   SYNCED   READY   COMPOSITION                          AGE
r1--tunnel0--d311cfe5   r1       Tunnel0     ipsec-ipv4    192.168.100.1/24   Replace   ready   1/1                   True     True    tunnelinterfaces.iosxe.netclab.dev   5m54s
r3--tunnel0--d311cfe5   r3       Tunnel0     ipsec-ipv4    192.168.100.2/24   Replace   ready   1/1                   True     True    tunnelinterfaces.iosxe.netclab.dev   5m54s
```

```console
r1#show crypto ikev2 sa detailed | include READY|Quantum
2         10.0.12.1/500         10.0.23.2/500         none/none            READY
      Quantum-safe Encryption using Manual PPK
```

## One Kubernetes object per configuration section

| kind | the section on the router |
|---|---|
| `Ikev2Proposal` | `crypto ikev2 proposal` |
| `Ikev2Policy` | `crypto ikev2 policy` |
| `Ikev2Keyring` | `crypto ikev2 keyring`: per peer a pre-shared key and, optionally, `ppk manual` |
| `Ikev2Profile` | `crypto ikev2 profile`, optionally with `keyring ppk`; pre-shared keys both ways, the one method of this version |
| `IpsecTransformSet` | `crypto ipsec transform-set` |
| `IpsecProfile` | `crypto ipsec profile` |
| `TunnelInterface` | `interface Tunnel` |

Each object names a `Device`: the router's RESTCONF address and credentials. The Device
configures nothing; its status lists the router's sections of the kinds above.

The keyring of r1 in part 9, with the PPK it shares with r3:

```yaml title="iosxe/examples/ikev2keyring/r1.yaml"
apiVersion: iosxe.netclab.dev/v1alpha1
kind: Ikev2Keyring
metadata:
  name: r1--classical-keyring--eb60cb7d
spec:
  managementPolicy: Replace
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

- The configuration is kept, not pushed: a change made by hand is put back, and the
  tunnel's state is read back into its object.
- The objects apply at once, in any order: each waits until its Device and the objects
  in its `after` are Ready.
- Keys live in Secrets, which the objects name, so the objects go to Git without them. A
  key changed in its Secret is written to every router whose object names it, and the
  peer's IKEv2 SA is renegotiated on it, as in [Rotate keys](keys.md).
- Each object has a mode: `Observe` reads, `Merge` writes the fields of its spec,
  `Replace` makes the section its spec. A router configured by hand is taken over one
  section at a time, as in [Adopt a router](adopt.md).
- The tunnel's object shows its interface state, and its IKEv2 SA with the other router:
  `active`, `pending` or `none`.
- Deleting the objects in `Replace` removes everything they configured.

The package supports tunnels with the PPK and without it, and pre-shared keys stored on
the router in clear or as type 6 (`password encryption aes`).

## Limits

- PPK, not ML-KEM. The Catalyst 8000V answers `IKEv2 PQC is not supported on this
  platform`: ML-KEM needs a Secure Router, C8100 to C8500. Part 12 of the series
  [automates it](https://github.com/juliogomez/pqc) over NETCONF, on the same YANG.
- Tested on Catalyst 8000V 17.18.02. The PPK lines go over `Cisco-IOS-XE-cli-rpc`, since
  the YANG of 17.18 has none, and the router gives no PPK back over RESTCONF.

## Quick start

### 1. The routers

On IOS XE 17.18, licensed for IPsec, RESTCONF and a user it accepts. The lab uses a local
user; [Adopt a router](adopt.md#before) says what the package needs of one.

```
username cisco privilege 15 secret cisco
ip http secure-server
ip http authentication local
restconf
```

RESTCONF answers:

```bash
curl -sk -u cisco:cisco -H 'Accept: application/yang-data+json' \
  https://<router>/restconf/data/Cisco-IOS-XE-native:native/hostname
```

```console
{
  "Cisco-IOS-XE-native:hostname": "r1"
}
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

```console
namespace/lab created
secret/ike-keys created
secret/iosxe-creds created
clusterproviderconfig.http.m.crossplane.io/default created
```

The namespace `lab`, the ClusterProviderConfig, and two Secrets: the routers' credentials
and the keys. The values are the lab's; change them in
`iosxe/scenarios/prerequisites/secrets.yaml` for your routers.

### 4. Next

- [Part 9](part9.md): two routers and a tunnel with the PPK, configured from nothing.
- [Adopt a router](adopt.md): routers that already have their IPsec configuration.
