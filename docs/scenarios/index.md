# Scenarios

The package offers several mechanisms for configuring the same device. Each one
is a directory under [`scenarios/`](https://github.com/netclab/netclab-xp/tree/main/scenarios)
holding manifests you can apply as they are.

| scenario | mechanism | what it configures |
|---|---|---|
| [`restconf`](restconf.md) | OpenConfig over RESTCONF | the base config — BGP, interfaces, routing |
| [`jsonrpc`](jsonrpc.md) | eAPI over JSON-RPC | settings OpenConfig does not model |
| [`eapi`](eapi.md) | raw EOS CLI | the same config, expressed as commands |
| [`router`](router.md) | the `Router` abstraction | one device from one resource |

!!! warning "Pick one mechanism per device"

    `restconf`, `eapi` and `router` each become an owner of the same
    configuration. Applying two of them to one device means two things editing
    the same lines. `jsonrpc` adds settings the others do not reach, and can sit
    alongside `restconf`.

## Before you start

Every command below runs from a clone of the repository — the scenarios are
manifests, not something the package installs:

```bash
git clone https://github.com/netclab/netclab-xp
cd netclab-xp
```

You also need [devices](../lab.md), the
[package installed, and its prerequisites applied](../install.md), and
[yq](https://github.com/mikefarah/yq#install) — removing a scenario filters the
rendered manifests through it.

## Applying a scenario

Every scenario is applied the same way; the directory name is the only thing
that changes. Substitute any row of the table above for `router` here and in the
teardown below.

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/router \
  | kubectl apply -f -
```

The flag is needed because the overlays reach into `examples/`, so that every
manifest exists in exactly one place. To use a different namespace, change
`namespace:` in that scenario's `kustomization.yaml` — the `Namespace` object
follows it.

## Removing a scenario

Filter the `Namespace` out of the delete:

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/router \
  | yq 'select(.kind != "Namespace")' \
  | kubectl delete -f -
```

Deleting the `Namespace` together with the resources inside it **deadlocks**.
The namespace begins terminating, which forbids creating anything in it — and
provider-http's cleanup path needs to create a tracking object there. The
requests keep their finalizers, the namespace waits for the requests, and
neither finishes without editing finalizers by hand.

Leaving the namespace behind is also the right outcome: it is yours, not the
scenario's.

!!! note "`kubectl delete` returns long before the device changes"

    The resources are gone in a fraction of a second, but the requests that
    talk to the device are cleaned up afterwards. Watch those, not the command:

    ```bash
    kubectl -n netclab get requests.http.m.crossplane.io -w
    ```

## Deleting resources strips the device

This is the part that surprises people, and it is the point of the package:
what Crossplane wrote, Crossplane removes. After deleting a `restconf`
scenario, the BGP instance is gone, `ip routing` is gone, the loopback does not
exist, and the ethernet interface is back to bare.

!!! tip "Readiness lags the device by one poll"

    A resource commonly reports `Ready=False` for a poll interval after its
    requests are already `Ready=True`, often next to
    `Responsive=False WatchCircuitOpen`. It clears on its own. Wait rather than
    debug it.

Each scenario's page carries its own apply and teardown commands, so the two
above are the general shape rather than something to adapt by hand.
