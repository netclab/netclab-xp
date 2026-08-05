# eAPI — the CLI, for everything else

The modelled layers reach what their models cover. This one reaches whatever the
CLI can say: an `EosCommand` carries EOS commands, and function-eapi turns them
into requests against the device.

On `ceos01` it sets `ip routing`, a loopback and a BGP instance, then the
peer-group scaffolding an EVPN design is built on: two peer groups, their
passwords, and which address family each is activated in. No neighbours are
assigned to those groups and no VXLAN interface exists, so nothing peers — what
the scenario shows is the shape of the commands, not a fabric that comes up.

## Running it

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/eapi \
  | kubectl apply -f -
```

## What lands on the device

Commands are nested the way the configuration is, not written as a flat script:

```yaml
apiVersion: eos.netclab.dev/v1alpha1
kind: EosCommand
metadata:
  name: eoscommand-33
spec:
  endpoint: ceos01.default.svc.cluster.local
  cmds:
    ip routing: {}
    interface Loopback0:
      ip address 10.255.0.1/32: {}
    router bgp 65001:
      router-id 10.255.0.1: {}
      no bgp default ipv4-unicast: {}
      neighbor EVPN-OVERLAY-PEERS peer group: {}
      neighbor EVPN-OVERLAY-PEERS update-source Loopback0: {}
```

The nesting is what a section is: keys under `router bgp 65001` are entered
inside it, and removal knows the difference between negating a line and taking
out the section around it.

What reaches the device is what you wrote:

```console
router bgp 65001
   router-id 10.255.0.1
   no bgp default ipv4-unicast
   maximum-paths 4 ecmp 4
   neighbor EVPN-OVERLAY-PEERS peer group
   neighbor EVPN-OVERLAY-PEERS next-hop-unchanged
   neighbor EVPN-OVERLAY-PEERS update-source Loopback0
   neighbor EVPN-OVERLAY-PEERS bfd
   neighbor EVPN-OVERLAY-PEERS ebgp-multihop 3
   neighbor EVPN-OVERLAY-PEERS password 7 Q4fqtbqcZ7oQuKfuWtNGRQ==
   neighbor EVPN-OVERLAY-PEERS send-community
   neighbor IPv4-UNDERLAY-PEERS peer group
   neighbor IPv4-UNDERLAY-PEERS password 7 7x4B4rnJhZB438m9+BrBfQ==
```

That literalness is the trade. Nothing is abstracted, so a setting no model
covers is still within reach — and nothing is checked for you either: a typo is
a command the device rejects, not a manifest the cluster refuses.

## Teardown

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone scenarios/eapi \
  | yq 'select(.kind != "Namespace")' \
  | kubectl delete -f -
```

The device comes back to bare, BGP instance included.
