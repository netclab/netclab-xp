# Adopt a router

A brownfield router, one that already has its IPsec configuration, is taken over one
section at a time, and every step is a pull request. Until a pull request grants it,
nothing is written to the router.

The example is r1 and r3 with the tunnel of [Part 9](part9.md) configured by hand, a
description on r1's Tunnel0, and a second proposal on r1, `LEGACY_PROPOSAL`.

## How the steps go

The objects are YAML files in a Git repository. Argo CD or Flux keeps the namespace `ipsec`
equal to the repository: what is merged is applied, what is removed is deleted. Each step
is a pull request that adds or changes files; once it is reviewed and merged, the cluster
has the objects within a sync, and the package acts on the routers. Without GitOps,
`kubectl apply -f <file>` does the same as a merge.

At the end the repository looks like this, one directory per router and one file per
object. Step 1 adds the `device.yaml` files, Step 3 one file per section, and the later
steps only change them:

```
├── r1
│   ├── device.yaml
│   ├── ikev2keyring
│   │   └── r1--classical-keyring--eb60cb7d.yaml
│   ├── ikev2policy
│   │   └── r1--classical-policy--17d97755.yaml
│   ├── ikev2profile
│   │   └── r1--classical-profile--cdf1f733.yaml
│   ├── ikev2proposal
│   │   ├── r1--classical-proposal--3a16aab3.yaml
│   │   └── r1--legacy-proposal--d8cc32e4.yaml
│   ├── ipsecprofile
│   │   └── r1--classical-ipsec--461c477a.yaml
│   ├── ipsectransformset
│   │   └── r1--classical-ts--771f3cb2.yaml
│   └── tunnelinterface
│       └── r1--tunnel0--d311cfe5.yaml
└── r3
    ├── device.yaml
    ├── ikev2keyring
    │   └── r3--classical-keyring--eb60cb7d.yaml
    ├── ikev2policy
    │   └── r3--classical-policy--17d97755.yaml
    ├── ikev2profile
    │   └── r3--classical-profile--cdf1f733.yaml
    ├── ikev2proposal
    │   └── r3--classical-proposal--3a16aab3.yaml
    ├── ipsecprofile
    │   └── r3--classical-ipsec--461c477a.yaml
    ├── ipsectransformset
    │   └── r3--classical-ts--771f3cb2.yaml
    └── tunnelinterface
        └── r3--tunnel0--d311cfe5.yaml
```

r3 has no `LEGACY_PROPOSAL`: that section is on r1 alone, and its object stays in `Observe`
through every step.

## The three modes

An object's spec is the intent: what the section is to be. Its status is what the router
has. Every object has a mode, `spec.managementPolicy`:

| mode | on the router | deleting the object |
|---|---|---|
| `Observe` (default) | reads the section, writes nothing | leaves the section |
| `Merge` | merges the intent into the section, and puts it back after a change by hand; the rest of the section stays | leaves the section |
| `Replace` | replaces the section with the intent: what the intent lacks is removed | removes the section |

`Observe` is the default, so an object that leaves the field out only reads. Keys follow
their own rules, in [Keys](#keys).

## Before

### The routers

Each router needs RESTCONF turned on, and a user that RESTCONF lets read and write the
configuration. The package sends the user's credentials with HTTP basic authentication
over HTTPS. Tested with a local user:

```
username <user> privilege 15 secret <password>
ip http secure-server
ip http authentication local
restconf
```

RESTCONF answers:

```bash
curl -sk -u <user>:<password> -H 'Accept: application/yang-data+json' \
  https://<router>/restconf/data/Cisco-IOS-XE-native:native/hostname
```

```console
{
  "Cisco-IOS-XE-native:hostname": "r1"
}
```

### The control plane

The package installed in a cluster that reaches the routers: the
[Quick start](index.md#2-the-cluster-and-the-package) for a new kind cluster, or
[Install the package](../eos/install.md#the-configuration) for one that runs Crossplane.

The Kubernetes resources the package needs beside it: a namespace, `ipsec` here, a Secret
with the routers' credentials, and a ClusterProviderConfig, the configuration of
provider-http, through which the package reaches the routers:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ipsec
---
apiVersion: v1
kind: Secret
metadata:
  name: iosxe-creds
  namespace: ipsec
stringData:
  basic: <base64 of user:password>
---
apiVersion: http.m.crossplane.io/v1alpha2
kind: ClusterProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: None
```

The Secret of the keys is not needed yet: Step 4 names it. Nothing below writes to a
router until Step 5.

## Step 1: Declare the devices

A pull request adds a Device per router:

```yaml title="r1/device.yaml"
apiVersion: iosxe.netclab.dev/v1alpha1
kind: Device
metadata:
  name: r1
spec:
  address: 172.18.0.101
  insecureSkipTLSVerify: true
  credentialsSecretRef:
    name: iosxe-creds
    key: basic
```

and `r3/device.yaml`, the same with r3's name and address. The routers of the example have
self-signed certificates, so the Device skips their verification. With a certificate that
provider-http trusts, leave `insecureSkipTLSVerify` out; this guide does not cover it.

After the merge and the sync:

```bash
kubectl wait --for=condition=Ready device --all -n ipsec --timeout=300s
kubectl get device -n ipsec
```

```console
device.iosxe.netclab.dev/r1 condition met
device.iosxe.netclab.dev/r3 condition met

NAME   ADDRESS        SYNCED   READY   COMPOSITION                 AGE
r1     172.18.0.101   True     True    devices.iosxe.netclab.dev   1s
r3     172.18.0.103   True     True    devices.iosxe.netclab.dev   1s
```

Router: unchanged. A Device is Ready when the router has answered with these credentials
and the Device has read the router's sections. A Device name has at most 31 characters and
no `--`.

## Step 2: See what is there

```bash
kubectl get device r1 -n ipsec -o yaml
```

```yaml
status:
  conditions:
  - lastTransitionTime: "2026-11-09T10:37:04Z"
    observedGeneration: 3
    reason: ReconcileSuccess
    status: "True"
    type: Synced
  - lastTransitionTime: "2026-11-09T10:37:05Z"
    observedGeneration: 3
    reason: Available
    status: "True"
    type: Ready
  - lastTransitionTime: "2026-11-09T10:37:04Z"
    observedGeneration: 3
    reason: WatchCircuitClosed
    status: "True"
    type: Responsive
  config:
  - exists: false
    kind: Ikev2Proposal
    name: CLASSICAL-PROPOSAL
    xr: r1--classical-proposal--3a16aab3
  - exists: false
    kind: Ikev2Proposal
    name: LEGACY_PROPOSAL
    xr: r1--legacy-proposal--d8cc32e4
  - exists: false
    kind: Ikev2Policy
    name: CLASSICAL-POLICY
    xr: r1--classical-policy--17d97755
  - exists: false
    kind: Ikev2Keyring
    name: CLASSICAL-KEYRING
    xr: r1--classical-keyring--eb60cb7d
  - exists: false
    kind: Ikev2Profile
    name: CLASSICAL-PROFILE
    xr: r1--classical-profile--cdf1f733
  - exists: false
    kind: IpsecTransformSet
    name: CLASSICAL-TS
    xr: r1--classical-ts--771f3cb2
  - exists: false
    kind: IpsecProfile
    name: CLASSICAL-IPSEC
    xr: r1--classical-ipsec--461c477a
  - exists: false
    kind: TunnelInterface
    name: Tunnel0
    xr: r1--tunnel0--d311cfe5
  vrfs: []
```

Each entry is a section on the router that one of the package's kinds models: `name` as
on the router, `xr` the name its object must have, and `exists` whether that object is in
the namespace. The rest of the router's configuration, BGP or ACLs for instance, is not
listed.

## Step 3, Observe: Import the sections

A pull request adds one thin object per section, copied from `status.config`:

```yaml title="r1/ikev2proposal/r1--classical-proposal--3a16aab3.yaml"
apiVersion: iosxe.netclab.dev/v1alpha1
kind: Ikev2Proposal
metadata:
  name: r1--classical-proposal--3a16aab3
spec:
  deviceRef:
    name: r1
  name: CLASSICAL-PROPOSAL
```

A thin object has only `deviceRef` and `name`, and no mode, so it observes. For many
sections, the objects come from the Device's status in one command:

```bash
kubectl get device r1 -n ipsec -o json | jq -r '.status.config[] | select(.exists | not) |
  "---\napiVersion: iosxe.netclab.dev/v1alpha1\nkind: \(.kind)\nmetadata:\n  name: \(.xr)\nspec:\n  deviceRef:\n    name: r1\n  name: \(.name | @json)"'
```

After the merge and the sync:

```bash
kubectl get ikev2proposal,tunnelinterface -n ipsec
```

```console
NAME                                                               DEVICE   PROPOSAL             MODE      WANTS-NAME   SYNCED   READY   COMPOSITION                        AGE
ikev2proposal.iosxe.netclab.dev/r1--classical-proposal--3a16aab3   r1       CLASSICAL-PROPOSAL   Observe                True     True    ikev2proposals.iosxe.netclab.dev   2m11s
ikev2proposal.iosxe.netclab.dev/r1--legacy-proposal--d8cc32e4      r1       LEGACY_PROPOSAL      Observe                True     True    ikev2proposals.iosxe.netclab.dev   2m11s
ikev2proposal.iosxe.netclab.dev/r3--classical-proposal--3a16aab3   r3       CLASSICAL-PROPOSAL   Observe                True     True    ikev2proposals.iosxe.netclab.dev   2m11s

NAME                                                      DEVICE   INTERFACE   TUNNEL-MODE   ADDRESS   MODE      OPER    IKE-SA   WANTS-NAME   SYNCED   READY   COMPOSITION                          AGE
tunnelinterface.iosxe.netclab.dev/r1--tunnel0--d311cfe5   r1       Tunnel0                             Observe   ready   1/1                   True     True    tunnelinterfaces.iosxe.netclab.dev   2m11s
tunnelinterface.iosxe.netclab.dev/r3--tunnel0--d311cfe5   r3       Tunnel0                             Observe   ready   1/1                   True     True    tunnelinterfaces.iosxe.netclab.dev   2m11s
```

Every entry of `status.config` has `exists: true`. Router: unchanged.

## Step 4, Observe: Write the intent from the status

Each object shows the section as the router has it, in the shape of its spec:

```bash
kubectl get ikev2proposal r1--classical-proposal--3a16aab3 -n ipsec -o yaml
```

```yaml
status:
  conditions:
  - lastTransitionTime: "2026-11-09T10:37:06Z"
    observedGeneration: 3
    reason: ReconcileSuccess
    status: "True"
    type: Synced
  - lastTransitionTime: "2026-11-09T10:37:08Z"
    observedGeneration: 3
    reason: Available
    status: "True"
    type: Ready
  - lastTransitionTime: "2026-11-09T10:37:06Z"
    observedGeneration: 3
    reason: WatchCircuitClosed
    status: "True"
    type: Responsive
  drift: []
  extra: []
  observed:
    encryption:
    - aes-cbc-256
    group:
    - 20
    integrity:
    - sha512
```

A pull request copies `status.observed` into `spec`, the intent:

```diff
 spec:
   deviceRef:
     name: r1
   name: CLASSICAL-PROPOSAL
+  encryption: [aes-cbc-256]
+  integrity: [sha512]
+  group: [20]
```

The keyring and the profile need more than `status.observed`: the references to the
Secrets of their keys, and the PPK's id and its keyring, which the router does not give
back; see [Keys](#keys). The profile:

```diff
 spec:
   deviceRef:
     name: r1
   name: CLASSICAL-PROFILE
+  keyring: CLASSICAL-KEYRING
+  remoteAddresses: [10.0.23.2]
+  ppkKeyring: CLASSICAL-KEYRING
```

Until Step 5 writes its mark, the profile shows its PPK keyring as drift:

```yaml
status:
  conditions:
  - lastTransitionTime: "2026-11-09T10:39:22Z"
    observedGeneration: 4
    reason: ReconcileSuccess
    status: "True"
    type: Synced
  - lastTransitionTime: "2026-11-09T10:39:22Z"
    observedGeneration: 4
    reason: Creating
    status: "False"
    type: Ready
  - lastTransitionTime: "2026-11-09T10:39:22Z"
    observedGeneration: 4
    reason: WatchCircuitClosed
    status: "True"
    type: Responsive
  drift:
  - device: []
    field: ppkKeyring
    spec:
    - CLASSICAL-KEYRING
  extra: []
  observed:
    keyring: CLASSICAL-KEYRING
    remoteAddresses:
    - 10.0.23.2
```

After a change by hand on r1, group 19 in place of 20, the proposal shows what of its spec
the router lacks, and what the router has beyond it:

```yaml
status:
  conditions:
  - lastTransitionTime: "2026-11-09T10:39:22Z"
    observedGeneration: 4
    reason: ReconcileSuccess
    status: "True"
    type: Synced
  - lastTransitionTime: "2026-11-09T10:42:22Z"
    observedGeneration: 4
    reason: Creating
    status: "False"
    type: Ready
  - lastTransitionTime: "2026-11-09T10:39:22Z"
    observedGeneration: 4
    reason: WatchCircuitClosed
    status: "True"
    type: Responsive
  drift:
  - device:
    - "19"
    field: group
    spec:
    - "20"
  extra:
  - device:
    - "19"
    field: group
  observed:
    encryption:
    - aes-cbc-256
    group:
    - 19
    integrity:
    - sha512
```

The object is not Ready while `drift` has an entry. While the router is still changed by
hand, each change shows as drift, and a pull request copies it from `status.observed` into
the intent. Step 5 ends this: from then on a change is made in the intent, in the
repository, and a change by hand is put back.

## Step 5, Merge the intent into the section

A pull request sets `Merge` on every object but `LEGACY_PROPOSAL`, which stays observed:

```diff
 spec:
+  managementPolicy: Merge
   deviceRef:
     name: r1
```

In `Merge` the intent is merged into the section. If the object was Ready before the pull
request, the router does not change: the intent already matches the section. `Merge` needs every field the router needs, so a thin object
is refused here. Taking over writes the keys' marks and the profile's `keyring ppk` with
its mark, and leaves the tunnel's SA as it is:

```yaml
status:
  conditions:
  - lastTransitionTime: "2026-11-09T10:45:05Z"
    observedGeneration: 6
    reason: ReconcileSuccess
    status: "True"
    type: Synced
  - lastTransitionTime: "2026-11-09T10:45:05Z"
    observedGeneration: 6
    reason: Available
    status: "True"
    type: Ready
  - lastTransitionTime: "2026-11-09T10:44:58Z"
    observedGeneration: 6
    reason: WatchCircuitClosed
    status: "True"
    type: Responsive
  drift: []
  extra: []
  keys:
  - path: peers[R3].preSharedKey
    written: true
  - path: peers[R3].ppk
    written: true
  missingSecrets: []
  observed:
    peers:
    - address: 10.0.23.2
      name: R3
      preSharedKey:
        present: true
  origin: TakenOver
```

From now on a change by hand to a field of the spec is put back at the next poll, and
recorded. A change to the section is a pull request to its intent.

`Merge` adds and corrects, and never removes. A field the spec leaves out is not
compared. A list in the spec has to be on the router, and what the router has beyond it
stays, as does the description on r1's Tunnel0. The same change by hand as in Step 4,
group 19 in place of 20, under `Merge`: 20 is put back, 19 stays and shows in
`status.extra`, and the object is Ready:

```yaml
status:
  conditions:
  - lastTransitionTime: "2026-11-09T10:44:59Z"
    observedGeneration: 5
    reason: ReconcileSuccess
    status: "True"
    type: Synced
  - lastTransitionTime: "2026-11-09T10:48:00Z"
    observedGeneration: 5
    reason: Available
    status: "True"
    type: Ready
  - lastTransitionTime: "2026-11-09T10:44:59Z"
    observedGeneration: 5
    reason: WatchCircuitClosed
    status: "True"
    type: Responsive
  drift: []
  extra:
  - device:
    - "19"
    field: group
  observed:
    encryption:
    - aes-cbc-256
    group:
    - 19
    - 20
    integrity:
    - sha512
  reverted:
    drift:
    - device:
      - "19"
      field: group
      spec:
      - "20"
    extra: []
    time: "2026-11-09T10:48:00Z"
```

Removing it from the router takes `Replace`.

## Step 6, Replace the section with the intent

Optional. In `Replace` the section is replaced with the intent: what the intent lacks is
removed at the next poll, so `status.extra` empties, and deleting the object removes the
section from the router. The object is Ready when the section is its intent. A pull request
sets it on every object but `LEGACY_PROPOSAL`, with `after`, as [Part 9](part9.md) has it,
so that an object is written after those it names:

```diff
 spec:
-  managementPolicy: Merge
+  managementPolicy: Replace
   deviceRef:
     name: r1
+  after:
+  - {kind: Ikev2Proposal, name: r1--classical-proposal--3a16aab3}
   name: CLASSICAL-POLICY
   proposals: [CLASSICAL-PROPOSAL]
```

At the next poll group 19 is taken off the router, and the description off Tunnel0:

```yaml
status:
  conditions:
  - lastTransitionTime: "2026-11-09T10:49:32Z"
    observedGeneration: 6
    reason: ReconcileSuccess
    status: "True"
    type: Synced
  - lastTransitionTime: "2026-11-09T10:49:35Z"
    observedGeneration: 6
    reason: Available
    status: "True"
    type: Ready
  - lastTransitionTime: "2026-11-09T10:49:31Z"
    observedGeneration: 6
    reason: WatchCircuitClosed
    status: "True"
    type: Responsive
  drift: []
  extra: []
  observed:
    encryption:
    - aes-cbc-256
    group:
    - 20
    integrity:
    - sha512
  reverted:
    drift: []
    extra:
    - device:
      - "19"
      field: group
    time: "2026-11-09T10:49:35Z"
---
status:
  conditions:
  - lastTransitionTime: "2026-11-09T10:49:33Z"
    observedGeneration: 8
    reason: ReconcileSuccess
    status: "True"
    type: Synced
  - lastTransitionTime: "2026-11-09T10:49:37Z"
    observedGeneration: 8
    reason: Available
    status: "True"
    type: Ready
  - lastTransitionTime: "2026-11-09T10:49:33Z"
    observedGeneration: 8
    reason: WatchCircuitClosed
    status: "True"
    type: Responsive
  drift: []
  extra: []
  observed:
    destination: 10.0.23.2
    ipsecProfile: CLASSICAL-IPSEC
    ipv4Address: 192.168.100.1/24
    mode: ipsec-ipv4
    source: GigabitEthernet2
  oper:
    activePeers: 1/1
    interface: ready
    peers:
    - address: 10.0.23.2
      ikeSA: active
  reverted:
    drift: []
    extra:
    - device:
      - '"by hand"'
      field: description
    time: "2026-11-09T10:49:37Z"
```

`Replace` writes the section's keys from their Secrets with every write of the
section, so the Secrets have to hold the keys the router has; see [Keys](#keys).

## Keys

A pre-shared key or a PPK is held in an entry of a Secret in the namespace, and the spec
names the Secret and the entry. Status never shows a key, and the router does not give one
back in a form that can be compared, so a key is never part of `status.drift`.

`status.observed` shows only whether a key is there. On IOS XE 17.18 a PPK is not shown at
all:

```yaml
status:
  observed:
    peers:
      - address: 10.0.23.2
        name: R3
        preSharedKey:
          present: true
```

In Step 4 the key becomes a reference to a Secret. The Secret holds the value the router
has, and is made outside the repository, or kept in it encrypted, as the team does with
other Secrets; the pull request adds only the reference, and the PPK's id:

```diff
 spec:
   deviceRef:
     name: r1
   name: CLASSICAL-KEYRING
+  peers:
+  - name: R3
+    address: 10.0.23.2
+    preSharedKeySecretRef:
+      name: ike-keys
+      key: psk
+    ppk:
+      id: PPK-R1R3
+      keySecretRef:
+        name: ike-keys
+        key: ppk-hex
```

Taking over in Step 5 writes no key, so a wrong value in the Secret does not reach the
router; Step 6, and any later write under `Replace`, writes it. Once the section is the
package's, a key is rotated in its Secret, as in [Rotate keys](keys.md).

## Going back

A pull request that lowers the mode, to `Merge` or to `Observe`, from any mode: the
router does not change, keys and marks included. Deleting an object in `Observe` or
`Merge` leaves its section on the router as it is:

```console
r3#show running-config | include ^interface Tunnel|^crypto ikev2|^crypto ipsec|ppk
crypto ikev2 proposal CLASSICAL-PROPOSAL
crypto ikev2 policy CLASSICAL-POLICY
crypto ikev2 keyring CLASSICAL-KEYRING
  ppk manual id PPK-R1R3 key hex 48656C6C6F506F737451756172746E756D Required
crypto ikev2 profile CLASSICAL-PROFILE
 keyring ppk CLASSICAL-KEYRING
crypto ipsec transform-set CLASSICAL-TS esp-gcm 256
crypto ipsec profile CLASSICAL-IPSEC
interface Tunnel0
event manager environment netclab-de309fce "eba0dc85 Ikev2Keyring/CLASSICAL-KEYRING/R1/ppk"
event manager environment netclab-96580d81 "eb60cb7d Ikev2Profile/CLASSICAL-PROFILE/ppk CLASSICAL-KEYRING"
```

A Device cannot be deleted while an object names it: the admission webhook denies it until
the objects are gone.

## Names

An object's name is `<device>--<slug>--<hash>`:

- `slug`: the name on the router in lower case; any character other than a letter or a
  digit becomes `-`, a run of them one `-`, none at either end, and the slug is cut so
  that the whole name fits 63 characters;
- `hash`: the first 8 hex digits of the SHA-256 of the name on the router.

The hash keeps names apart that differ only in case or punctuation, and the name fits the
63 characters Kubernetes allows whatever the router accepts. `status.config` gives the
name, so it never has to be worked out by hand.

A second object for the same section has the same name, so kustomize and the API server
refuse it: two objects in a namespace never write one section, as long as each router has
one Device. An object under another name writes nothing, and its status gives the name it
needs:

```console
$ kubectl get ikev2proposal -n ipsec
NAME                               DEVICE   PROPOSAL             MODE      WANTS-NAME                      SYNCED   READY   COMPOSITION                        AGE
my-proposal                        r1       LEGACY_PROPOSAL      Observe   r1--legacy-proposal--d8cc32e4   True     False   ikev2proposals.iosxe.netclab.dev   2m10s
r1--classical-proposal--3a16aab3   r1       CLASSICAL-PROPOSAL   Observe                                   True     True    ikev2proposals.iosxe.netclab.dev   2m10s
r1--legacy-proposal--d8cc32e4      r1       LEGACY_PROPOSAL      Observe                                   True     True    ikev2proposals.iosxe.netclab.dev   2m10s
r3--classical-proposal--3a16aab3   r3       CLASSICAL-PROPOSAL   Observe                                   True     True    ikev2proposals.iosxe.netclab.dev   2m10s
```

The fix is a pull request that renames the file and `metadata.name`. The object under the
wrong name never wrote anything, so deleting it leaves the router as it is.

`spec.name` and `deviceRef` cannot change: the name follows from them. A section under a
new name, or on another router, is a new object.
