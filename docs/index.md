---
hide:
  - navigation
---

# netclab-xp

Crossplane Configuration packages that turn router configuration into Kubernetes
resources: versioned, reviewable, and reconciled like anything else in a cluster.

| package | devices | over |
|---|---|---|
| `configuration-eos` | Arista EOS | RESTCONF, JSON-RPC (eAPI) |
| `configuration-iosxe` | Cisco IOS XE | RESTCONF |
| `configuration-aws-vpn` | Cisco IOS XE and AWS | RESTCONF, the AWS API |

Each package installs on its own, from its own tags (`eos/v*`, `iosxe/v*`, `aws-vpn/v*`),
and all run in one cluster.

<div class="grid cards" markdown>

- **[Arista EOS](eos/index.md)**

    One API over several mechanisms, from one setting up to a whole router, with a
    lab of two cEOS and runnable scenarios.

- **[Post-quantum IPsec on IOS XE](iosxe/index.md)**

    An IPsec tunnel between Cisco routers with a post-quantum preshared key mixed
    into IKEv2, as Kubernetes objects kept on the routers by reconcile.

- **[Site-to-Site VPN to AWS](aws-vpn/index.md)**

    A router on premises and an AWS gateway, both sides from one object, with keys
    rotated one tunnel at a time.

</div>
