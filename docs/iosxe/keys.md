# Rotate keys

A pre-shared key or a PPK is held in an entry of a Secret, and the keyring names the
Secret and the entry. A rotation is a change of the entry's value: the package writes the
new key to every router whose keyring names it, and the IKEv2 SA between them is set up
again on it. Here it is done on the tunnel of [Part 9](part9.md).

## Where a key lives

The keyring of r1 names the Secret `ike-keys` for both keys, each by its entry, `key:`:

```yaml title="iosxe/examples/ikev2keyring/r1.yaml"
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

r3's keyring names the same Secret, so one change reaches both ends. The keyrings go to Git;
the Secret is made outside the repository, or kept in it encrypted, as the team does with
other Secrets.

Status never shows a key. `status.keys` says, per key, whether the router holds the value in
the Secret:

```bash
kubectl get ikev2keyring r1--classical-keyring--eb60cb7d -n lab -o jsonpath='{.status.keys}'
```

```console
<from the run>
```

The router does not give a key back in a form that can be compared, so a key is never part
of `status.drift`.

## Before

[Part 9](part9.md) applied, its tunnel up:

```bash
kubectl get tunnelinterface -n lab
```

```console
<from the run>
```

## Rotate the PPK

The PPK is hex of ASCII characters, the one form the router accepts:

```bash
kubectl patch secret ike-keys -n lab --type merge \
  -p "{\"stringData\":{\"ppk-hex\":\"$(printf %s RotatedPostQuantum | xxd -p -u)\"}}"
```

Within seconds the new key is on r1 and r3. Writing a key clears the peer's IKEv2 SA,
since an SA in place would go on without the new key: the tunnel interface goes line
protocol down and carries no traffic until IKEv2 sets up a new SA on the new key.
`kubectl get tunnelinterface` shows it in `OPER` and `IKE-SA`:

```bash
kubectl get tunnelinterface -n lab -w
```

```console
<from the run>
```

The new SA, on the PPK:

```console
r1#show crypto ikev2 sa detailed | include READY|Quantum
<from the run>
```

## Rotate the pre-shared key

The same, with the entry `psk`:

```bash
kubectl patch secret ike-keys -n lab --type merge -p '{"stringData":{"psk":"RotatedPsk456"}}'
```

```console
<from the run>
```

## When a key is written

| event | the key on the router |
|---|---|
| taking over a section that exists, as in [Adopt a router](adopt.md) | not written |
| the value of the key's entry changes in its Secret | written, on every router whose keyring names it |
| `Replace`, any write of the section | written |
| the Secret is deleted and made again | written once |
| the annotation `iosxe.netclab.dev/rewrite-keys` changes | written once |

Taking over writes no key, so a wrong value in the Secret does not reach the router.

## Write a key again

A key changed on the router by hand is not seen, since the router does not give it back.
The annotation writes the keys of a keyring again, from its Secret:

```bash
kubectl annotate ikev2keyring r1--classical-keyring--eb60cb7d -n lab \
  iosxe.netclab.dev/rewrite-keys=1
```

```console
<from the run>
```

Another value of the annotation writes them once more.

## A missing Secret

A Secret or an entry that the keyring names and the namespace lacks is listed, as
`<Secret>/<entry>`, and nothing new is written for the keyring until it exists:

```yaml
status:
  missingSecrets: [ike-keys/psk]
```

The keyring is not Ready, and nothing is taken off the router: the tunnel goes on with the
keys it has.

## The marks

To tell which value it wrote, the package keeps a mark of each key, never the key, in an
EEM environment variable on the router named `netclab-` and 8 hex digits. A rotation
changes the mark on both ends:

```console
r1#show running-config | include ^event manager environment netclab-
<from the run>
```
