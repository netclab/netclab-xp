# Site-to-Site VPN to AWS

`configuration-aws-vpn` connects a Cisco IOS XE router on premises to an AWS virtual private
gateway or transit gateway. One Kubernetes object, a `Connection`, makes the VPN connection
on AWS and both tunnels on the router, keeps them there by reconcile, and shows both sides
in its status:

```console
$ kubectl get connection -n lab
NAME        DEVICE   REGION      TUNNEL1   TUNNEL2   ROTATION   SYNCED   READY   COMPOSITION                       AGE
edge1-aws   edge1    us-east-1   ready     ready                True     True    connections.aws-vpn.netclab.dev   9m25s
```

## One object for both sides

The Connection is in the words of the AWS console: a customer gateway (the router), a
target gateway (the gateway on AWS) and two tunnels.

The example in the repository, `aws-vpn/examples/connection/edge1.yaml`:

```yaml
apiVersion: aws-vpn.netclab.dev/v1alpha1
kind: Connection
metadata:
  name: edge1-aws
  namespace: lab
spec:
  customerGateway:
    deviceRef:
      name: edge1                  # the router's Device, from configuration-iosxe
    ipAddress: 203.0.113.10        # the router's public address, outside any NAT
    bgpAsn: 65010
    source: GigabitEthernet2       # where the tunnels' packets leave from
    outsideVrf: WAN                # the source's VRF; optional
    ikev2ProfileSpec:              # AWS's recommended settings, see AWS's sample
      dpd: {interval: 10, retry: 10, query: on-demand}
      lifetime: 28800
    ipsecProfileSpec:
      pfs: group20
      lifetime: 3600
      dfbit: clear
      replayWindowSize: 128
    tunnelInterfaceSpec:
      tcpAdjustMss: 1379
  targetGateway:
    region: us-east-1
    vpnGatewayId: vgw-0123456789abcdef0   # or transitGatewayId
  tunnels:
  - interface: Tunnel1
    insideCidr: 169.254.10.0/30
    preSharedKeySecretRef: {name: edge1-aws-keys, key: tunnel1}
  - interface: Tunnel2
    insideCidr: 169.254.10.4/30
    preSharedKeySecretRef: {name: edge1-aws-keys, key: tunnel2}
```

What it makes, each named after the Connection:

| where | what | how |
|---|---|---|
| AWS | `CustomerGateway`, `VPNConnection` | provider-aws-ec2 |
| router | `Ikev2Keyring`, `Ikev2Profile`, `IpsecTransformSet` (esp-gcm 256), `IpsecProfile` (`pfs group14` unless `ipsecProfileSpec.pfs`), a `TunnelInterface` per tunnel | configuration-iosxe, `Replace` |
| cluster | the Secret `<connection>-applied-keys`, which both ends read their keys from | |

The tunnels' outside addresses and AWS's inside addresses are AWS's: the router side is
made once AWS gives them, and read back from the VPN connection, never derived.

`ikev2ProfileSpec`, `ipsecProfileSpec` and `tunnelInterfaceSpec` take the fields of
configuration-iosxe's `Ikev2Profile`, `IpsecProfile` and `TunnelInterface`, which validate
them, except those the Connection sets itself. [AWS's sample](sample.md) maps AWS's own
configuration for a Cisco router onto them, line by line.

## Status from both sides

```bash
kubectl get connection edge1-aws -n lab -o jsonpath='{.status}' | jq
```

```yaml
router:                      # read from the router
  tunnels:
  - {interface: Tunnel1, address: 169.254.10.2/30, oper: ready, bgp: established}
  - {interface: Tunnel2, address: 169.254.10.6/30, oper: ready, bgp: established}
aws:                         # read from the VPN connection
  vpnConnectionId: vpn-0de913e273365c0a6
  customerGatewayId: cgw-03da78dce229ac8cf
  tunnels:
  - {outsideAddress: 34.194.185.77, insideAddress: 169.254.10.1, bgpAsn: "64512", oper: UP, message: 0 BGP ROUTES}
  - {outsideAddress: 52.207.103.185, insideAddress: 169.254.10.5, bgpAsn: "64512", oper: UP, message: 0 BGP ROUTES}
keys:                        # marks of the keys, never the keys
- {interface: Tunnel1, wanted: d3031a23, applied: d3031a23}
- {interface: Tunnel2, wanted: de5c8830, applied: de5c8830}
```

The columns read `router`: AWS's telemetry follows the router by minutes.

## What it does

- Both sides from one object, kept by reconcile: a change by hand on the router is put
  back, and deleting the Connection removes the VPN connection on AWS and everything it
  configured on the router.
- Keys live in a Secret, which the Connection names, so the Connection goes to Git without
  them. A key changed there is rotated one tunnel at a time, the other carrying traffic
  throughout, as in [Rotate keys](keys.md).
- The router's IKEv2 policy and proposal are left alone: one policy serves every peer of a
  local address, so a policy the package wrote would change the router's other VPNs. A
  router without one uses its `default` policy, which AWS's defaults accept.
- BGP stays the user's: the router's `router bgp` is configured by hand or by other tools,
  and the Connection reads each session to AWS from the router.

## Limits

- IOS XE only, BGP routing only (`routing: Dynamic`).
- The gateway on AWS exists already; the package never creates it.
- Made by the package only: a VPN connection made by hand is not taken over.
- Two Connections with one router address, in one account and region, share AWS's customer
  gateway: AWS returns the existing one, and the first one's delete waits for the second.
- Tested on Catalyst 8000V 17.18, behind NAT, with provider-aws-ec2 v2.9.4.

## Quick start

### 1. The cluster and the package

As for [IPsec on IOS XE](../iosxe/index.md#2-the-cluster-and-the-package), with this
package; it brings configuration-iosxe and function-aws-vpn with it:

```bash
CROSSPLANE=<release>   # a Crossplane v2 release
VERSION=<version>      # the newest aws-vpn/v* tag, without aws-vpn/

uvx netclab up --cluster xp --crossplane ${CROSSPLANE} \
  --configuration xpkg.upbound.io/netclab/configuration-aws-vpn:${VERSION}
```

### 2. The AWS provider

The package does not install provider-aws-ec2 itself. A cluster that already runs it would
get a second Provider of the same package from the dependency, and the two collide on its
CRDs; so a cluster that has it keeps its own. On a clean cluster, provider-family-aws
first, then provider-aws-ec2, at one version, `v2.0.0` or later:

```bash
EC2_VERSION=<version>   # a provider-aws-ec2 release

for p in provider-family-aws provider-aws-ec2; do
  kubectl apply -f - <<EOF
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: upbound-$p
spec:
  package: xpkg.upbound.io/upbound/$p:${EC2_VERSION}
EOF
  kubectl wait --for=condition=Healthy provider/upbound-$p --timeout=10m
done
```

Its credentials, an access key of an account that may manage VPN connections, in the
ClusterProviderConfig `default`, which the Connection uses unless
`targetGateway.providerConfigRef` names another:

```bash
printf '[default]\naws_access_key_id = %s\naws_secret_access_key = %s\n' \
  "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" \
  | kubectl -n crossplane-system create secret generic aws-creds --from-file=credentials=/dev/stdin

kubectl apply -f - <<EOF
apiVersion: aws.m.upbound.io/v1beta1
kind: ClusterProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: Secret
    secretRef: {namespace: crossplane-system, name: aws-creds, key: credentials}
EOF
```

### 3. The router

RESTCONF as in [IPsec on IOS XE](../iosxe/index.md#1-the-routers), and a route from the
outside interface, in `outsideVrf` if set, to AWS's outside addresses; behind NAT,
`ipAddress` is the address outside it. From a clone of the repository, the namespace `lab`,
the router's credentials and provider-http's ClusterProviderConfig:

```bash
git clone https://github.com/netclab/netclab-xp
cd netclab-xp

kubectl apply -k iosxe/scenarios/prerequisites
```

Then the router's Device:

```yaml
apiVersion: iosxe.netclab.dev/v1alpha1
kind: Device
metadata:
  name: edge1
  namespace: lab
spec:
  address: <router>               # its RESTCONF address
  insecureSkipTLSVerify: true
  credentialsSecretRef:
    name: iosxe-creds
    key: basic
```

### 4. The keys and the Connection

```bash
kubectl -n lab create secret generic edge1-aws-keys \
  --from-literal=tunnel1=<key> --from-literal=tunnel2=<key>
```

AWS's rules for a key: 8 to 64 characters, letters, digits, periods and underscores, not
starting with zero. Then the Connection, with the router's public address and the gateway's
ID in `aws-vpn/examples/connection/edge1.yaml`:

```bash
kubectl apply -f aws-vpn/examples/connection/edge1.yaml
kubectl get connection -n lab -w
```

AWS makes the VPN connection available after 7 to 11 minutes; the router side follows.

### 5. BGP

AWS's inside addresses and ASN come into `status.aws.tunnels`:

```bash
kubectl get connection edge1-aws -n lab \
  -o jsonpath='{range .status.aws.tunnels[*]}{.insideAddress} {.bgpAsn}{"\n"}{end}'
```

```console
169.254.10.1 64512
169.254.10.5 64512
```

A neighbour for each, on the router:

```
router bgp 65010
 neighbor 169.254.10.1 remote-as 64512
 neighbor 169.254.10.5 remote-as 64512
```

With `insideVrf`, the neighbours go under that VRF's address family. `TUNNEL1` and
`TUNNEL2` say `ready` and `status.router.tunnels[].bgp` `established`.
