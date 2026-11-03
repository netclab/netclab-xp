# Brownfield with GitOps

A router that already has its IPsec configuration is taken over one block at a time, and
every step is a pull request. Until a pull request grants it, nothing is written to the
router.

The example is r1 with two blocks configured by hand, `CLASSICAL-PROPOSAL` and
`LEGACY_PROPOSAL`, and a repository that Argo CD or Flux syncs into the namespace `lab`.

## The three modes

Every object has `spec.managementPolicy`:

| mode | on the router | deleting the object |
|---|---|---|
| `Observe` (default) | reads the block, writes nothing | leaves the block |
| `Manage` | writes the fields of its spec, and puts them back after a change by hand; the rest of the block stays | leaves the block |
| `FullControl` | makes the block its spec: what the spec lacks is removed | removes the block |

`Observe` is the default, so an object that leaves the field out only reads. Keys follow
their own rules, in [Keys](#keys).

## Prerequisites

- The package installed, at a version that has `managementPolicy`.
- RESTCONF on the router, as in the [Quick start](index.md#1-the-routers).
- A Secret in the namespace whose key holds the base64 of `<user>:<password>`, as `basic`
  in `iosxe-creds` below.

## Step 1: Declare the device

Pull request:

```yaml
# r1/device.yaml
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

Cluster, after the sync:

```console
$ kubectl get device r1 -n lab
NAME   SYNCED   READY
r1     True     True
```

Router: unchanged. `Ready` means the router answered with these credentials. A Device
name has at most 31 characters and no `--`.

## Step 2: See what is there

```console
$ kubectl get device r1 -n lab -o yaml
```

```yaml
status:
  sections:
  - kind: Ikev2Proposal
    name: CLASSICAL-PROPOSAL
    xr: r1--classical-proposal--3a16aab3
    exists: false
  - kind: Ikev2Proposal
    name: LEGACY_PROPOSAL
    xr: r1--legacy-proposal--d8cc32e4
    exists: false
```

Each section is a block on the router of a kind the package knows: `name` as on the
router, `xr` the name its object must have, and `exists` whether that object is in the
namespace. Blocks of other kinds, such as BGP or ACLs, are not listed.

## Step 3: Import

Pull request with one thin object per section, copied from `status.sections`:

```yaml
# r1/ikev2proposal/r1--classical-proposal--3a16aab3.yaml
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
blocks, the objects come from the Device's status in one command:

```bash
kubectl get device r1 -n lab -o json | jq -r '.status.sections[] | select(.exists | not) |
  "---\napiVersion: iosxe.netclab.dev/v1alpha1\nkind: \(.kind)\nmetadata:\n  name: \(.xr)\nspec:\n  deviceRef:\n    name: r1\n  name: \(.name | @json)"'
```

Cluster, after the sync: every section has `exists: true`. Router: unchanged.

## Step 4: Catch up with the router

Each object shows the block as the router has it, in the shape of its spec:

```console
$ kubectl get ikev2proposal r1--classical-proposal--3a16aab3 -n lab -o yaml
```

```yaml
status:
  observed:
    encryption: [aes-cbc-256]
    integrity: [sha512]
    group: [19]
  drift: []
```

Pull request: `status.observed` copied into `spec`.

```diff
 spec:
   deviceRef:
     name: r1
   name: CLASSICAL-PROPOSAL
+  encryption: [aes-cbc-256]
+  integrity: [sha512]
+  group: [19]
```

After a change by hand, the object shows where its spec is behind:

```yaml
status:
  drift:
  - field: group
    device: ["20"]
    spec: ["19"]
```

The object is not Ready while `drift` has an entry. While the router is still changed by
hand, each change shows as drift, and a pull request copies it from `status.observed` into
`spec`. Step 5 ends this: from then on a change is made in the repository, and a change by
hand is put back.

## Step 5: Take over

Pull request:

```diff
 spec:
+  managementPolicy: Manage
   deviceRef:
     name: r1
   name: CLASSICAL-PROPOSAL
   encryption: [aes-cbc-256]
   integrity: [sha512]
   group: [19]
```

If the object was Ready before the pull request, the router does not change: its spec
already matches the block. `Manage` needs every field the router needs, so a thin object
is refused here.

From now on a change by hand to a field of the spec is put back at the next poll, within a
minute, and recorded:

```yaml
status:
  reverted:
    time: "2026-11-02T11:57:13Z"
    drift:
    - field: group
      device: ["20"]
      spec: ["19"]
```

A change to the block is a pull request to its spec.

`Manage` adds and corrects, and never removes. A field the spec leaves out is not compared.
A list in the spec has to be on the router, and what the router has beyond it stays: a
second group added by hand, or a group a pull request removes from the spec. It shows in
`status.extra` and leaves the object Ready:

```yaml
status:
  drift: []
  extra:
  - field: group
    device: ["20"]
```

Removing it from the router takes `FullControl`.

## Step 6: Full control

Optional. With `FullControl` the block on the router is the spec: what the spec lacks is
removed at the next poll, so `status.extra` empties, and deleting the object removes the
block from the router. The object is Ready when the block is its spec.

```diff
 spec:
-  managementPolicy: Manage
+  managementPolicy: FullControl
```

`FullControl` writes the block's keys from their Secrets with every write of the block, so
the Secrets have to hold the keys the router has; see [Keys](#keys).

## Keys

A pre-shared key or a PPK is held in a Secret in the namespace, and the spec names the
Secret and its key. Status never shows a key, and the router does not give one back in a
form that can be compared, so a key is never part of `status.drift`.

`status.observed` shows only whether a key is there. On IOS XE 17.18 a PPK is not shown at
all:

```yaml
# r1/ikev2keyring/r1--classical-keyring--<hash>.yaml, status after Step 3
status:
  observed:
    peers:
    - name: R3
      address: 10.0.23.2
      preSharedKey: {present: true, encryption: "6"}
```

In Step 4 the key becomes a reference to a Secret, which the same pull request adds with
the value the router holds:

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
| Step 5, taking over a block that exists | not written |
| the key's value changes in its Secret | written, on every router whose object names it |
| `FullControl`, any write of the block | written |
| the annotation `iosxe.netclab.dev/rewrite-keys` changes | written once |

Taking over writes no key, so a wrong value in the Secret does not reach the router. A
rotation is a pull request that changes the value in the Secret, and both ends of a tunnel
that name the same Secret get the new key. Writing a PPK renews the tunnel's SA.

To tell which value it wrote, the package keeps a mark of each key, never the key, in an
EEM environment variable on the router named `netclab-` and 8 hex digits:

```console
r1#show running-config | include ^event manager environment netclab-
event manager environment netclab-5c1e07aa "3f2a9c01 Ikev2Keyring/CLASSICAL-KEYRING/peers/R3/preSharedKey"
```

## Going back

A pull request that lowers the mode: `FullControl` to `Manage`, or `Manage` to
`Observe`. The router does not change. Deleting an object in `Observe` or `Manage` leaves
its block on the router as it is.

## Names

An object's name is `<device>--<slug>--<hash>`:

- `slug`: the name on the router in lower case; any character other than a letter or a
  digit becomes `-`, a run of them one `-`, and the slug is cut so that the whole name
  fits 63 characters;
- `hash`: the first 8 hex digits of the SHA-256 of the name on the router.

The hash keeps names apart that differ only in case or punctuation, and the name fits the
63 characters Kubernetes allows whatever the router accepts. `status.sections` gives the
name, so it never has to be worked out by hand.

A second object for the same block has the same name, so kustomize and the API server
refuse it: two objects in a namespace never write one block, as long as each router has
one Device. An object under another name writes nothing, and its status gives the name it
needs:

```console
$ kubectl get ikev2proposal -n lab
NAME                               DEVICE   PROPOSAL             READY   WANTS-NAME
r1--classical-proposal--3a16aab3   r1       CLASSICAL-PROPOSAL   True
my-proposal                        r1       LEGACY_PROPOSAL      False   r1--legacy-proposal--d8cc32e4
```

The fix is a pull request that renames the file and `metadata.name`. The object under the
wrong name never wrote anything, so deleting it leaves the router as it is.

`spec.name` and `deviceRef` cannot change: the name follows from them. A block under a new
name, or on another router, is a new object.
