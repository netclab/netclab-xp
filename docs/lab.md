# Set up a lab

Every scenario in this documentation is written against two Arista cEOS devices
called `ceos01` and `ceos02`, running as pods in the `default` namespace. This
page gets you there from an empty machine.

If you already have reachable devices, skip to
[installing the package](install.md) — nothing here is required, it is just the
lab the examples assume.

## Before you start

| tool | why |
|---|---|
| [docker](https://docs.docker.com/engine/install/) | runs the cluster and imports the cEOS image |
| [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) | the cluster itself — what this is tested on |
| [kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/) | everything else |
| [helm](https://helm.sh/docs/intro/install/) | installs the devices, and Crossplane on the next page |

You also need a **cEOS image**, which is licensed and cannot be pulled — see
below.

!!! note "Memory"

    Each cEOS device asks for 2Gi, so this lab needs 4Gi of headroom on top of
    the cluster itself. The [fabric scenario](scenarios/fabric.md) runs on two
    devices of its own and doubles that.

## Create a cluster

```bash
kind create cluster --name netclab
```

Every command below assumes that name.

## The cEOS image

cEOS is licensed. You download the tarball from Arista, import it, and load it
into the cluster's nodes:

```bash
docker import ./cEOS64-lab-4.36.1F.tar ceos:4.36.1F
kind load docker-image ceos:4.36.1F --name netclab
```

Check it arrived:

```bash
docker exec netclab-control-plane crictl images | grep ceos
```

```console
docker.io/library/ceos    4.36.1F    <image id>    934MB
```

Nothing in this project can distribute the image for you.

!!! tip "Rebuilding the cluster often?"

    `kind load` puts the image inside the node, so deleting the cluster costs
    you the import. Pushing it to a local registry backed by a docker volume
    instead makes it survive teardown — that is what `scripts/up.sh` does, and
    why this repository's own `scripts/topology.yaml` names
    `localhost:5001/netclab/ceos:4.36.1F` rather than `ceos:4.36.1F`.

## Multus and the CNI plugins

netclab-chart attaches each device's interfaces through Multus, using the
`bridge` and `host-device` plugins. Install both onto every node:

```bash
for node in $(kind get nodes --name netclab); do
  docker exec "$node" bash -c "curl -sSL \
    https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz \
    | tar -xz -C /opt/cni/bin ./bridge ./host-device"
done

kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/v4.3.0/deployments/multus-daemonset.yml
kubectl -n kube-system wait --for=jsonpath='{.status.numberReady}'=1 \
  --timeout=5m daemonset.apps/kube-multus-ds
```

Without this the devices come up with no interfaces at all.

## The topology

```bash
helm repo add netclab https://netclab.github.io/netclab-chart
helm repo update netclab
```

Two cEOS nodes on one bridge, cabled `eth1` to `eth1`:

```yaml title="topology.yaml"
topology:
  networks:
  - name: b1
    type: bridge
  nodes:
  - name: ceos01
    type: ceos
    image: ceos:4.36.1F
    memory: 2Gi
    cpu: 1000m
    interfaces:
    - name: eth1
      network: b1
  - name: ceos02
    type: ceos
    image: ceos:4.36.1F
    memory: 2Gi
    cpu: 1000m
    interfaces:
    - name: eth1
      network: b1
```

```bash
helm upgrade --install lab netclab/netclab --version 0.5.11 -n default -f topology.yaml
```

!!! danger "The names and the namespace are load-bearing"

    The chart creates a Service named after each node, and every example
    addresses its device as `ceos01.default.svc.cluster.local`. Rename the nodes
    or install into another namespace and the examples stop resolving.

    Both devices are needed even though only the `router` scenario uses the
    second one — that is the scenario with two routers and an eBGP session
    between them.

`0.5.11` is a floor rather than a preference. Below it, cEOS RESTCONF either
never came up, or came up and did not survive a container restart — so a lab on
an older chart fails in ways that look like the package is broken.

## Wait for the devices

cEOS takes roughly two minutes to boot, and **there is nothing to wait on**: a
pod reports `Running` long before EOS has finished starting, and the chart no
longer runs a Job whose completion you could watch.

The honest signal is the device answering:

```bash
for n in ceos01 ceos02; do
  kubectl -n default exec $n -- Cli -p 15 -c 'show management api restconf' | head -2
done
```

You are looking for RESTCONF enabled and running on port 6020:

```console
Enabled: yes
Server: running on port 6020, in default VRF
```

## Next

[Install the package](install.md), then apply
[your first resource](first-resource.md) or pick a
[scenario](scenarios/index.md).

The [fabric scenario](scenarios/fabric.md) is the exception: it pushes a
device's entire running configuration, so it runs on two devices of its own
rather than on `ceos01`/`ceos02`. Its page adds them to the cluster you just
built — everything above is shared.

!!! tip "Working on the package itself?"

    `scripts/up.sh` in the repository builds everything above in one command —
    registry, cluster, Crossplane, Multus, devices — and installs the package
    **built from your working tree** rather than a published release. That makes
    it a contributor tool, not the path described here.
