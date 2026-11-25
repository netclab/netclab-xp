# AWS's sample

The AWS console gives a configuration to paste on the router: "Download configuration" on
the VPN connection. It has no sample for IOS XE 16 or 17; the nearest, and the one with
IKEv2, is "Cisco Systems, Inc." / "CSRv AMI" / "IOS 12.4+" / "ikev2" / "recommended". Here
it is line by line against the Connection, for tunnel 1; tunnel 2 repeats it with its own
addresses.

| AWS's sample | the Connection |
|---|---|
| `crypto ikev2 proposal PROPOSAL1` <br> `encryption aes-gcm-256`, `prf sha384`, `group 20` | not made: the router's `default` |
| `crypto ikev2 policy POLICY1` <br> `match address local ...`, `proposal PROPOSAL1` | not made: a policy serves every peer of the local address, so it would change the router's other VPNs. AWS's defaults accept the router's `default` policy; configuration-iosxe's `Ikev2Proposal` and `Ikev2Policy` make one by hand |
| `crypto ikev2 keyring KEYRING1` <br> `peer`, `address <AWS's outside address>`, `pre-shared-key` | made: one keyring for both tunnels, each peer's key from `tunnels[].preSharedKeySecretRef` |
| `crypto ikev2 profile IKEV2-PROFILE` <br> `match address local ...` | made, without `match address local`: the profile matches AWS's addresses, and with `outsideVrf` `match fvrf` |
| `match identity remote address <AWS's outside address>` | made, both tunnels' addresses |
| `authentication remote pre-share`, `authentication local pre-share`, `keyring local KEYRING1` | made |
| `lifetime 28800` | `ikev2ProfileSpec.lifetime: 28800` |
| `dpd 10 10 on-demand` | `ikev2ProfileSpec.dpd: {interval: 10, retry: 10, query: on-demand}` |
| `crypto ipsec transform-set ... esp-gcm 256`, `mode tunnel` | made |
| `crypto ipsec profile ...` <br> `set pfs group20` | `ipsecProfileSpec.pfs: group20`; without it `set pfs group14` |
| `set security-association lifetime seconds 3600` | `ipsecProfileSpec.lifetime: 3600` |
| `set transform-set ...`, `set ikev2-profile IKEV2-PROFILE` | made |
| `crypto ipsec df-bit clear` | `ipsecProfileSpec.dfbit: clear`, in the profile rather than for the whole router |
| `crypto ipsec security-association replay window-size 128` | `ipsecProfileSpec.replayWindowSize: 128`, in the profile |
| `crypto isakmp keepalive 10 10` | not made: IKEv1 |
| `crypto ipsec fragmentation before-encryption` | not made: a setting of the whole router |
| `interface Tunnel1` <br> `ip address 169.254.10.2 255.255.255.252` | made, the address read back from the VPN connection |
| `ip virtual-reassembly` | not made: for NAT or a zone-based firewall on the tunnel |
| `tunnel source ...` | `customerGateway.source` |
| `tunnel destination <AWS's outside address>` | made |
| `tunnel mode ipsec ipv4`, `tunnel protection ipsec profile ...` | made |
| `ip tcp adjust-mss 1379` | `tunnelInterfaceSpec.tcpAdjustMss: 1379` |
| `router bgp 65010` ... `neighbor 169.254.10.1 remote-as 64512` | not made: BGP stays the user's, and the Connection reads the session |

The settings AWS recommends go through `ikev2ProfileSpec`, `ipsecProfileSpec` and
`tunnelInterfaceSpec`, with no defaults; what the tunnels need to work, the Connection sets
itself. PFS is both: required, so `group14` is set, and its group recommended, so
`ipsecProfileSpec.pfs` replaces it. Without PFS, a rekey by the router drops the tunnel for
15 to 21 seconds.
