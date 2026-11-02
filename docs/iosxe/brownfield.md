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
| `Manage` | writes the block, and puts it back after a change by hand | leaves the block |
| `FullControl` | as `Manage` | removes the block |

`Observe` is the default, so an object that leaves the field out only reads.

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

From now on a change by hand is put back at the next poll, within a minute, and recorded:

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

## Step 6: Full control

Optional. With `FullControl`, deleting the object also removes the block from the router:

```diff
 spec:
-  managementPolicy: Manage
+  managementPolicy: FullControl
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
