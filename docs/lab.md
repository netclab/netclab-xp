# Set up a lab

Every scenario in this documentation is written against two Arista cEOS devices
called `ceos01` and `ceos02`, running as pods in the `default` namespace. This
page gets you there.

If you already have reachable devices, skip to
[installing the package](install.md) — nothing here is required, it is just the
lab the examples assume.

## What you need

| | |
|---|---|
| a Kubernetes cluster | [kind](https://kind.sigs.k8s.io) is fine, and is what this is tested on |
| Multus and two CNI plugins | the devices get extra interfaces; without this they come up with none |
| a cEOS image | licensed by Arista — see below |
| [netclab-chart](https://github.com/netclab/netclab-chart) `>=0.5.11` | runs the devices |
| Crossplane | for the package itself |

!!! warning "The cEOS image cannot be pulled"

    cEOS is licensed. You download it from Arista, import it yourself, and push
    it somewhere your cluster can reach:

    ```bash
    docker tag ceos:4.36.1F <your-registry>/netclab/ceos:4.36.1F
    docker push <your-registry>/netclab/ceos:4.36.1F
    ```

    On kind, that means a registry the node's containerd trusts. Nothing in
    this project can distribute the image for you.

## Multus and the CNI plugins

netclab-chart attaches each device's interfaces through Multus, using the
`bridge` and `host-device` plugins. On kind, install both onto every node:

```bash
for node in $(kind get nodes --name <cluster>); do
  docker exec "$node" bash -c "curl -sSL \
    https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz \
    | tar -xz -C /opt/cni/bin ./bridge ./host-device"
done

kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/v4.3.0/deployments/multus-daemonset.yml
kubectl -n kube-system wait --for=jsonpath='{.status.numberReady}'=1 \
  --timeout=5m daemonset.apps/kube-multus-ds
```

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
    image: <your-registry>/netclab/ceos:4.36.1F
    memory: 2Gi
    cpu: 1000m
    interfaces:
    - name: eth1
      network: b1
  - name: ceos02
    type: ceos
    image: <your-registry>/netclab/ceos:4.36.1F
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
Enabled:            Yes
Server: running on port 6020, in default VRF
```

## Next

[Install the package](install.md), then pick a
[scenario](scenarios/index.md).

!!! tip "Working on the package itself?"

    `scripts/up.sh` in the repository builds everything above in one command —
    registry, cluster, Crossplane, Multus, devices — and installs the package
    **built from your working tree** rather than a published release. That makes
    it a contributor tool, not the path described here.
