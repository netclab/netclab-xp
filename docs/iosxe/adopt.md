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
<from the run>
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
<from the run>
```

Router: unchanged. A Device is Ready when the router has answered with these credentials
and the Device has read the router's sections. A Device name has at most 31 characters and
no `--`.

## Step 2: See what is there

```bash
kubectl get device r1 -n ipsec -o yaml
```

```yaml
<status.config of r1, from the run>
```

Each entry is a section on the router of a kind the package knows: `name` as on the
router, `xr` the name its object must have, and `exists` whether that object is in the
namespace. Sections of other kinds, such as BGP or ACLs, are not listed.

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
<from the run>
```

Every entry of `status.config` has `exists: true`. Router: unchanged.

## Step 4, Observe: Write the intent from the status

Each object shows the section as the router has it, in the shape of its spec:

```bash
kubectl get ikev2proposal r1--classical-proposal--3a16aab3 -n ipsec -o yaml
```

```yaml
<status of the proposal, from the run>
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
<status of the profile, from the run>
```

After a change by hand on r1, group 19 in place of 20, the proposal shows what of its spec
the router lacks, and what the router has beyond it:

```yaml
<status of the proposal after the change, from the run>
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
<status of the keyring, from the run>
```

From now on a change by hand to a field of the spec is put back at the next poll, and
recorded. A change to the section is a pull request to its intent.

`Merge` adds and corrects, and never removes. A field the spec leaves out is not
compared. A list in the spec has to be on the router, and what the router has beyond it
stays, as does the description on r1's Tunnel0. The same change by hand as in Step 4,
group 19 in place of 20, under `Merge`: 20 is put back, 19 stays and shows in
`status.extra`, and the object is Ready:

```yaml
<status of the proposal, from the run>
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
<status of the proposal and the tunnel, from the run>
```

`Replace` writes the section's keys from their Secrets with every write of the
section, so the Secrets have to hold the keys the router has; see [Keys](#keys).

## Keys

A pre-shared key or a PPK is held in a Secret in the namespace, and the spec names the
Secret and its key. Status never shows a key, and the router does not give one back in a
form that can be compared, so a key is never part of `status.drift`.

`status.observed` shows only whether a key is there. On IOS XE 17.18 a PPK is not shown at
all:

```yaml
<status.observed of r1's keyring, from the run>
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

A Secret that the spec names and the namespace lacks is listed, and nothing is written for
the object until it exists:

```yaml
status:
  missingSecrets: [ike-keys/psk]
```

When a key is written:

| event | the key on the router |
|---|---|
| Step 5, taking over a section that exists | not written |
| the key's value changes in its Secret | written, on every router whose object names it |
| `Replace`, any write of the section | written |
| the Secret is deleted and made again | written once |
| the annotation `iosxe.netclab.dev/rewrite-keys` changes | written once |

Taking over writes no key, so a wrong value in the Secret does not reach the router. A
rotation changes the value in the Secret, and both ends of a tunnel that name the same
Secret get the new key within seconds. Writing a key clears the peer's IKEv2 SA, since an
SA in place would go on without the new key. The tunnel interface goes line protocol down
and carries no traffic until IKEv2 sets up a new SA on the new key;
`kubectl get tunnelinterface` shows it in `OPER` and `IKE-SA`.

The annotation, on r1's keyring:

```bash
kubectl annotate ikev2keyring r1--classical-keyring--eb60cb7d -n ipsec \
  iosxe.netclab.dev/rewrite-keys=1
```

```console
<marks and SA, from the run>
```

While a Secret the spec names is missing, the object is not Ready, nothing is taken off the
router, and nothing new is written.

To tell which value it wrote, the package keeps a mark of each key, never the key, in an
EEM environment variable on the router named `netclab-` and 8 hex digits:

```console
r1#show running-config | include ^event manager environment netclab-
<from the run>
```

## Going back

A pull request that lowers the mode, to `Merge` or to `Observe`, from any mode: the
router does not change, keys and marks included. Deleting an object in `Observe` or
`Merge` leaves its section on the router as it is:

```console
<r3 after its objects lowered to Observe and deleted, from the run>
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
<from the run, with my-proposal>
```

The fix is a pull request that renames the file and `metadata.name`. The object under the
wrong name never wrote anything, so deleting it leaves the router as it is.

`spec.name` and `deviceRef` cannot change: the name follows from them. A section under a
new name, or on another router, is a new object.
