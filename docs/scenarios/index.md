# Scenarios

The package offers several mechanisms for configuring the same device. Each one
is a directory under [`scenarios/`](https://github.com/netclab/netclab-xp/tree/main/scenarios)
holding manifests you can apply as they are.

| scenario | mechanism | what it configures |
|---|---|---|
| [`restconf`](https://github.com/netclab/netclab-xp/tree/main/scenarios/restconf) | OpenConfig over RESTCONF | the base config — BGP, interfaces, routing |
| [`jsonrpc`](https://github.com/netclab/netclab-xp/tree/main/scenarios/jsonrpc) | eAPI over JSON-RPC | settings OpenConfig does not model |
| [`eapi`](https://github.com/netclab/netclab-xp/tree/main/scenarios/eapi) | raw EOS CLI | the same config, expressed as commands |
| [`router`](https://github.com/netclab/netclab-xp/tree/main/scenarios/router) | the `Router` abstraction | one device from one resource |
| [`fabric`](fabric.md) | an AVD design | a whole network from one model |

!!! warning "Pick one mechanism per device"

    `restconf`, `eapi` and `router` each become an owner of the same
    configuration. Applying two of them to one device means two things editing
    the same lines. `jsonrpc` adds settings the others do not reach, and can sit
    alongside `restconf`.

    `fabric` is different in kind — it configures a whole network and runs on
    devices of its own.

## Prerequisites

Installing the package brings in provider-http and the functions it needs, but
not the `ClusterProviderConfig`, `EnvironmentConfig` and credentials `Secret`
that the compositions reference by name. Apply those once:

```bash
kubectl apply -k scenarios/prerequisites
```

All three are cluster-wide, so this is a one-time step no matter which namespace
you put resources in.

`fabric` does not use these — it has
[its own set](https://github.com/netclab/netclab-xp/tree/main/scenarios/fabric/prerequisites).

## Applying a scenario

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
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/jsonrpc \
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

**`fabric` behaves the opposite way** — it pushes a device's entire running
configuration, so a teardown that reverted it would wipe the switch. It stops
managing what it wrote and leaves it in place. See
[the fabric walkthrough](fabric.md#teardown-leaves-the-device-configured).

!!! tip "Readiness lags the device by one poll"

    A resource commonly reports `Ready=False` for a poll interval after its
    requests are already `Ready=True`, often next to
    `Responsive=False WatchCircuitOpen`. It clears on its own. Wait rather than
    debug it.

## Documentation status

The [fabric walkthrough](fabric.md) is written. Pages for `restconf`,
`jsonrpc`, `eapi` and `router` are still to come — until then, each scenario's
`kustomization.yaml` carries the commands for applying and removing it.
