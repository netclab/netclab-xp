# Rotate keys

Each tunnel's pre-shared key is an entry of a Secret that the Connection names. A rotation
is a change of the entry's value: the Connection gives the new key to AWS and to the router
together, one tunnel at a time, so that the other tunnel carries traffic throughout.

!!! warning "Change the Secret the Connection names, never `<connection>-applied-keys`"
    The keys are changed in the Secret of `tunnels[].preSharedKeySecretRef`, here
    `edge1-aws-keys`. `edge1-aws-applied-keys` is the Connection's own: it holds what both
    ends have, and the Connection writes it back on its next pass.

## Where a key lives

```yaml
  tunnels:
  - interface: Tunnel1
    insideCidr: 169.254.10.0/30
    preSharedKeySecretRef: {name: edge1-aws-keys, key: tunnel1}
  - interface: Tunnel2
    insideCidr: 169.254.10.4/30
    preSharedKeySecretRef: {name: edge1-aws-keys, key: tunnel2}
```

Both ends read their keys from a Secret of the Connection's own,
`<connection>-applied-keys`: the VPN connection on AWS and the router's keyring. It equals
the user's Secret except during a rotation, while it holds the old key of the tunnel whose
turn has not come.

Status never shows a key. `status.keys` shows a mark of each, the one in the user's Secret
and the one both ends have:

```yaml
keys:
- {interface: Tunnel1, wanted: d3031a23, applied: d3031a23}
- {interface: Tunnel2, wanted: de5c8830, applied: de5c8830}
```

## Rotate

Both keys at once, in the user's Secret:

```bash
kubectl -n lab create secret generic edge1-aws-keys \
  --from-literal=tunnel1=<new key> --from-literal=tunnel2=<new key> \
  --dry-run=client -o yaml | kubectl apply -f -
```

The Connection gives tunnel 1 its new key; AWS rebuilds that tunnel, which goes down until
it is up again on the new key; then tunnel 2 takes its turn. A tunnel's turn ends when it is
up, its IKE SA active and its BGP session established. A run against AWS, the columns of
`kubectl get connection -n lab -w` against the seconds since the keys changed:

| s | TUNNEL1 | TUNNEL2 | ROTATION | `status.rotation.step` |
|---|---|---|---|---|
| 0 | ready | ready | | |
| 51 | ready | ready | Tunnel1 | sent |
| 136 | lower-layer-down | ready | Tunnel1 | down |
| 267 | ready | ready | Tunnel2 | sent |
| 327 | ready | lower-layer-down | Tunnel2 | down |
| 748 | ready | ready | | |

AWS's rebuild of a tunnel took 3 to 10 minutes. `status.rotation` names the tunnel whose
turn it is, and its step: `sent` once both ends have its new key, `down` while AWS rebuilds
it:

```yaml
rotation:
  awsTunnel: 2
  interface: Tunnel2
  step: down
  since: "2026-11-25T13:58:38Z"
```

One key changed rotates that tunnel alone.

## When both keys go at once

| the tunnels | the new keys |
|---|---|
| one or both up | one tunnel at a time, the other up |
| both down | both at once: nothing carries traffic, and a wrong key can be mended |

A tunnel whose turn has come but which is never seen down counts as rotated after 20 minutes
up.

## A missing Secret

A Secret or an entry that the Connection names and the namespace lacks is listed, as
`<Secret>/<entry>`:

```yaml
status:
  missingSecrets: [edge1-aws-keys/tunnel2]
```

The tunnels go on with the keys they have.

## AWS's rules for a key

8 to 64 characters: letters, digits, periods and underscores, not starting with zero.
