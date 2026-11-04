#!/bin/bash
# Records the router's answers to the GETs the compositions observe with, in each state
# the objects of iosxe/examples/ can be in.
#
#   PEER=<address> iosxe/tests/record.sh <router-address> <ios-xe-version> [kind...]
#
# Writes iosxe/tests/fixtures/<ios-xe-version>/<kind>/, and secrets.json with the values
# the router held, which the tests put in place of {{ name:namespace:key }}. Kinds run in
# apply order, all of them when none is named. Leaves nothing behind on the router.
# PEER, which tunnelinterface needs, is the router at the tunnel's destination, its
# GigabitEthernet2 at 10.0.23.2: it gets the far end for the tunnel's state while it is up.
# Credentials: IOSXE_USER and IOSXE_PASSWORD, cisco/cisco by default.
set -euo pipefail

ADDR=${1:?router address}
VERSION=${2:?IOS XE version, e.g. 17.18.02}
shift 2
FIXTURES=$(cd "$(dirname "$0")" && pwd)/fixtures/$VERSION
AUTH=${IOSXE_USER:-cisco}:${IOSXE_PASSWORD:-cisco}
BASE=https://$ADDR/restconf
NATIVE=$BASE/data/Cisco-IOS-XE-native:native

# apply order
KINDS=(device ikev2proposal ikev2policy ikev2keyring ikev2profile ipsectransformset ipsecprofile tunnelinterface)

# the values the examples' Secrets hold, and their uid in the tests (conftest.py)
PSK=TestPsk123
PPK_HEX=48656C6C6F506F737451756172746E756D   # "HelloPostQuartnum"
SECRET_UID=00000000-0000-4000-8000-000000000001
b64() { printf %s "$1" | base64 -w0; }
sha8() { printf %s "$1" | sha256sum | cut -c1-8; }

curl_() { curl -sk -m 60 -u "$AUTH" -H 'Accept: application/yang-data+json' \
  -H 'Content-Type: application/yang-data+json' "$@"; }

# A change from outside RESTCONF starts a sync that locks the datastore (409 lock-denied).
waitsync() {
  local t0=$SECONDS
  until curl_ -X POST "$BASE/operations/cisco-ia:is-syncing" \
      | jq -e '.["cisco-ia:output"] | (.syncing | not) and (.["running-datastore-locked"] | not)' > /dev/null; do
    [ $((SECONDS - t0)) -lt 120 ] || { echo "still syncing after 120 s" >&2; exit 1; }
    sleep 2
  done
}

write() { # write <method> <url> [body]: fails unless the router answers 2xx
  waitsync
  local code
  code=$(curl_ -o /dev/null -w '%{http_code}' -X "$1" "$2" ${3:+--data-binary "$3"})
  case $code in 2??) ;; *) echo "$1 $2: HTTP $code" >&2; exit 1 ;; esac
}

absent() { # absent <url>: deleted, or never there
  waitsync
  curl_ -o /dev/null -X DELETE "$1"
}

cli() { # cli <lines>: config-ios-cli-rpc, fails unless the RPC succeeds
  waitsync
  curl_ -X POST "$BASE/operations/Cisco-IOS-XE-cli-rpc:config-ios-cli-rpc" \
    --data-binary "$(jq -nc --arg c "$1" '{"Cisco-IOS-XE-cli-rpc:input":{"config-clis":$c}}')" \
    | jq -e '.["Cisco-IOS-XE-cli-rpc:output"].result == "RPC request successful"' > /dev/null
}

until_() { # until_ <what> <command>...: until the command succeeds, for at most 180 s
  local what=$1 t0=$SECONDS; shift
  until "$@"; do
    [ $((SECONDS - t0)) -lt 180 ] || { echo "not $what after 180 s" >&2; exit 1; }
    sleep 2
  done
}

onpeer() { # onpeer <command>...: the command's writes and waits on PEER
  local BASE=https://$PEER/restconf
  "$@"
}

record() { # record <kind>/<state> <url>: the status code and the body, as the provider sees them
  waitsync
  local body code
  body=$(mktemp)
  code=$(curl_ -o "$body" -w '%{http_code}' "$2")
  mkdir -p "$(dirname "$FIXTURES/$1")"
  jq -n --argjson code "$code" --rawfile body "$body" \
    '{statusCode: $code, body: ($body | try fromjson catch $body)}' > "$FIXTURES/$1.json"
  rm -f "$body"
  echo "$1: HTTP $code"
}

patch() { # patch <kind>/<state> <body>: Manage's PATCH on native, sent and recorded with
  # the router's answer; fails unless 2xx
  waitsync
  local body code
  body=$(mktemp)
  code=$(curl_ -o "$body" -w '%{http_code}' -X PATCH "$NATIVE" --data-binary "$2")
  jq -n --arg url "$NATIVE" --argjson sent "$2" --argjson code "$code" --rawfile body "$body" \
    '{request: {method: "PATCH", url: $url, body: $sent}, statusCode: $code,
      body: ($body | try fromjson catch $body)}' > "$FIXTURES/$1.json"
  rm -f "$body"
  echo "$1: HTTP $code"
  case $code in 2??) ;; *) exit 1 ;; esac
}

rpc() { # rpc <kind>/<state> <lines>: config-ios-cli-rpc, sent and recorded with the
  # router's answer; fails unless the RPC succeeds
  waitsync
  local sent out
  sent=$(jq -nc --arg c "$2" '{"Cisco-IOS-XE-cli-rpc:input":{"config-clis":$c}}')
  out=$(mktemp)
  curl_ -o "$out" -X POST "$BASE/operations/Cisco-IOS-XE-cli-rpc:config-ios-cli-rpc" --data-binary "$sent"
  jq -n --arg url "$BASE/operations/Cisco-IOS-XE-cli-rpc:config-ios-cli-rpc" --argjson sent "$sent" \
    --slurpfile body "$out" '{request: {method: "POST", url: $url, body: $sent}, body: $body[0]}' > "$FIXTURES/$1.json"
  rm -f "$out"
  echo "$1: $(jq -r '.body["Cisco-IOS-XE-cli-rpc:output"].result' "$FIXTURES/$1.json")"
  jq -e '.body["Cisco-IOS-XE-cli-rpc:output"].result == "RPC request successful"' "$FIXTURES/$1.json" > /dev/null
}

device() { # the names the Device reads, before and with part 9's blocks and LEGACY_PROPOSAL
  local config="$NATIVE/crypto?fields=Cisco-IOS-XE-crypto:ikev2(proposal/name;policy/name;keyring/name;profile/name);Cisco-IOS-XE-crypto:ipsec(transform-set/tag;profile/name)"
  local tunnels="$NATIVE/interface?fields=Tunnel/name"
  local crypto=$NATIVE/crypto/Cisco-IOS-XE-crypto
  record device/config-absent "$config"
  record device/tunnels-absent "$tunnels"
  write PUT "$crypto:ikev2/proposal=CLASSICAL-PROPOSAL" '{"Cisco-IOS-XE-crypto:proposal": [{"name": "CLASSICAL-PROPOSAL",
    "encryption": {"aes-cbc-256": [null]}, "integrity": {"sha512": [null]}, "group": {"twenty": [null]}}]}'
  write PUT "$crypto:ikev2/proposal=LEGACY_PROPOSAL" '{"Cisco-IOS-XE-crypto:proposal": [{"name": "LEGACY_PROPOSAL",
    "encryption": {"aes-cbc-128": [null]}, "integrity": {"sha256": [null]}, "group": {"fourteen": [null]}}]}'
  write PUT "$crypto:ikev2/policy=CLASSICAL-POLICY" '{"Cisco-IOS-XE-crypto:policy": [{"name": "CLASSICAL-POLICY",
    "proposal": [{"proposals": "CLASSICAL-PROPOSAL"}]}]}'
  write PUT "$crypto:ikev2/keyring=CLASSICAL-KEYRING" "$(jq -nc --arg psk "$PSK" '{"Cisco-IOS-XE-crypto:keyring": [{name: "CLASSICAL-KEYRING",
    peer: [{name: "R3", address: {ipv4: {"ipv4-address": "10.0.23.2"}}, "pre-shared-key": {key: $psk}}]}]}')"
  write PUT "$crypto:ikev2/profile=CLASSICAL-PROFILE" '{"Cisco-IOS-XE-crypto:profile": [{"name": "CLASSICAL-PROFILE",
    "authentication": {"local": {"pre-share": {}}, "remote": {"pre-share": {}}}, "keyring": {"local": {"name": "CLASSICAL-KEYRING"}},
    "match": {"identity": {"remote": {"address": {"ipv4": [{"ipv4-address": "10.0.23.2", "ipv4-mask": "255.255.255.255"}]}}}}}]}'
  write PUT "$crypto:ipsec/transform-set=CLASSICAL-TS" '{"Cisco-IOS-XE-crypto:transform-set": [{"tag": "CLASSICAL-TS",
    "esp": "esp-gcm", "key-bit": "256", "mode": {"tunnel-choice": [null]}}]}'
  write PUT "$crypto:ipsec/profile=CLASSICAL-IPSEC" '{"Cisco-IOS-XE-crypto:profile": [{"name": "CLASSICAL-IPSEC",
    "set": {"transform-set": ["CLASSICAL-TS"], "ikev2-profile": "CLASSICAL-PROFILE"}}]}'
  write PUT "$NATIVE/interface/Tunnel=0" '{"Cisco-IOS-XE-native:Tunnel": [{"name": 0,
    "ip": {"address": {"primary": {"address": "192.168.100.1", "mask": "255.255.255.0"}}},
    "Cisco-IOS-XE-tunnel:tunnel": {"source": "GigabitEthernet2", "destination-config": {"ipv4": "10.0.23.2"},
    "mode": {"ipsec": {"ipv4-mode": {}, "ipv4": {}}},
    "protection": {"Cisco-IOS-XE-crypto:ipsec": {"profile-option": {"name": "CLASSICAL-IPSEC"}}}}}]}'
  record device/config-part9 "$config"
  record device/tunnels-part9 "$tunnels"
  write DELETE "$NATIVE/interface/Tunnel=0"
  write DELETE "$crypto:ipsec/profile=CLASSICAL-IPSEC"
  write DELETE "$crypto:ipsec/transform-set=CLASSICAL-TS"
  write DELETE "$crypto:ikev2/profile=CLASSICAL-PROFILE"
  write DELETE "$crypto:ikev2/keyring=CLASSICAL-KEYRING"
  write DELETE "$crypto:ikev2/policy=CLASSICAL-POLICY"
  write DELETE "$crypto:ikev2/proposal=LEGACY_PROPOSAL"
  write DELETE "$crypto:ikev2/proposal=CLASSICAL-PROPOSAL"
}

ikev2proposal() { # iosxe/examples/ikev2proposal/r1.yaml
  local url=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/proposal=CLASSICAL-PROPOSAL
  local example='{"name": "CLASSICAL-PROPOSAL", "encryption": {"aes-cbc-256": [null]},
    "integrity": {"sha512": [null]}, "group": {"twenty": [null]}}'
  put() { # put <jq update of the example>: one field differs per state
    write PUT "$url" "$(jq -nc --argjson p "$example" "{\"Cisco-IOS-XE-crypto:proposal\": [\$p | $1]}")"
  }
  absent "$url"
  record ikev2proposal/proposal-absent "$url"

  put .
  record ikev2proposal/proposal-applied "$url"
  put '.encryption += {"aes-cbc-128": [null]}'
  record ikev2proposal/proposal-extra-encryption "$url"
  put '.integrity = {"sha384": [null]}'
  record ikev2proposal/proposal-other-integrity "$url"
  put '.prf = {"sha384": [null]}'
  record ikev2proposal/proposal-with-prf "$url"
  put '.group = {"nineteen": [null]}'
  record ikev2proposal/proposal-other-group "$url"
  # Manage's write over group 19 alone: a merge keeps 19 beside the example's 20
  patch ikev2proposal/proposal-patch \
    "$(jq -nc --argjson p "$example" '{"Cisco-IOS-XE-native:native": {crypto: {"Cisco-IOS-XE-crypto:ikev2": {proposal: [$p]}}}}')"
  record ikev2proposal/proposal-patched "$url"

  write DELETE "$url"
}

ikev2policy() { # iosxe/examples/ikev2policy/r1.yaml, on the proposal of iosxe/examples/ikev2proposal/
  local url=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/policy=CLASSICAL-POLICY
  local proposal=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/proposal=CLASSICAL-PROPOSAL
  local example='{"name": "CLASSICAL-POLICY", "proposal": [{"proposals": "CLASSICAL-PROPOSAL"}]}'
  put() { # put <jq update of the example>: one field differs per state
    write PUT "$url" "$(jq -nc --argjson p "$example" "{\"Cisco-IOS-XE-crypto:policy\": [\$p | $1]}")"
  }
  absent "$url"
  record ikev2policy/policy-absent "$url"

  write PUT "$proposal" '{"Cisco-IOS-XE-crypto:proposal": [{"name": "CLASSICAL-PROPOSAL",
    "encryption": {"aes-cbc-256": [null]}, "integrity": {"sha512": [null]}, "group": {"twenty": [null]}}]}'
  put .
  record ikev2policy/policy-applied "$url"
  put '.proposal += [{"proposals": "default"}]'
  record ikev2policy/policy-extra-proposal "$url"
  put '.proposal = [{"proposals": "default"}]'
  record ikev2policy/policy-other-proposal "$url"
  put '.match = {"fvrf": {"any": [null]}}'
  record ikev2policy/policy-with-match "$url"
  # Manage's write over `default` alone: a merge keeps it beside the example's proposal
  put '.proposal = [{"proposals": "default"}]'
  patch ikev2policy/policy-patch \
    "$(jq -nc --argjson p "$example" '{"Cisco-IOS-XE-native:native": {crypto: {"Cisco-IOS-XE-crypto:ikev2": {policy: [$p]}}}}')"
  record ikev2policy/policy-patched "$url"

  write DELETE "$url"
  write DELETE "$proposal"
}

ikev2keyring() { # iosxe/examples/ikev2keyring/r1.yaml
  local url=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/keyring=CLASSICAL-KEYRING
  local eem=$NATIVE/event/Cisco-IOS-XE-eem:manager/environment
  body() { # body [psk]: the example's keyring, without a PSK when none is given
    jq -nc --arg psk "${1:-}" '{"Cisco-IOS-XE-crypto:keyring": [{name: "CLASSICAL-KEYRING", peer: [{name: "R3",
      address: {ipv4: {"ipv4-address": "10.0.23.2"}}} + if $psk == "" then {} else {"pre-shared-key": {key: $psk}} end]}]}'
  }
  absent "$url"
  record ikev2keyring/keyring-absent "$url"

  write PUT "$url" "$(body "$PSK")"
  record ikev2keyring/keyring-applied "$url"
  cli "crypto ikev2 keyring CLASSICAL-KEYRING
 peer R3
  ppk manual id PPK-R1R3 key hex $PPK_HEX required
  description made by hand"
  record ikev2keyring/keyring-described "$url"
  write PUT "$url" "$(body OtherPsk456)"
  record ikev2keyring/keyring-other-psk "$url"
  write PUT "$url" "$(body)"
  record ikev2keyring/keyring-no-psk "$url"

  # The marks of the examples' keys, as the composition makes them from SECRET_UID.
  local key place var mark
  for key in psk ppk; do
    place=Ikev2Keyring/CLASSICAL-KEYRING/R3/$key
    var=netclab-$(sha8 "$place")
    if [ $key = psk ]; then mark=$(sha8 "$SECRET_UID/$(b64 "$PSK")")
    else mark=$(sha8 "$SECRET_UID/$(b64 "$PPK_HEX")/PPK-R1R3"); fi
    absent "$eem=$var"
    record ikev2keyring/$key-mark-absent "$eem=$var"
    write PUT "$eem=$var" "$(jq -nc --arg n "$var" --arg v "$mark $place" '{"Cisco-IOS-XE-eem:environment": [{name: $n, value: $v}]}')"
    record ikev2keyring/$key-mark-applied "$eem=$var"
    write PUT "$eem=$var" "$(jq -nc --arg n "$var" --arg v "00000000 $place" '{"Cisco-IOS-XE-eem:environment": [{name: $n, value: $v}]}')"
    record ikev2keyring/$key-mark-other "$eem=$var"
    write DELETE "$eem=$var"
  done

  write DELETE "$url"
}

ikev2profile() { # iosxe/examples/ikev2profile/r1.yaml, on a keyring CLASSICAL-KEYRING
  local url=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/profile=CLASSICAL-PROFILE
  local keyring=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/keyring=CLASSICAL-KEYRING
  local example='{"name": "CLASSICAL-PROFILE", "authentication": {"local": {"pre-share": {}}, "remote": {"pre-share": {}}},
    "keyring": {"local": {"name": "CLASSICAL-KEYRING"}},
    "match": {"identity": {"remote": {"address": {"ipv4": [{"ipv4-address": "10.0.23.2", "ipv4-mask": "255.255.255.255"}]}}}}}'
  put() { # put <jq update of the example>: one field differs per state
    write PUT "$url" "$(jq -nc --argjson p "$example" "{\"Cisco-IOS-XE-crypto:profile\": [\$p | $1]}")"
  }
  absent "$url"
  record ikev2profile/profile-absent "$url"

  write PUT "$keyring" "$(jq -nc --arg psk "$PSK" '{"Cisco-IOS-XE-crypto:keyring": [{name: "CLASSICAL-KEYRING", peer: [{name: "R3",
    address: {ipv4: {"ipv4-address": "10.0.23.2"}}, "pre-shared-key": {key: $psk}}]}]}')"
  put .
  record ikev2profile/profile-applied "$url"

  # `keyring ppk`, which no read returns, and a description made by hand
  cli "crypto ikev2 profile CLASSICAL-PROFILE
 keyring ppk CLASSICAL-KEYRING
 description made by hand"
  record ikev2profile/profile-described "$url"

  # The mark of the example's PPK keyring, as the composition makes it.
  local eem=$NATIVE/event/Cisco-IOS-XE-eem:manager/environment
  local place=Ikev2Profile/CLASSICAL-PROFILE/ppk
  local var=netclab-$(sha8 "$place")
  absent "$eem=$var"
  record ikev2profile/ppk-mark-absent "$eem=$var"
  # the line and its mark in one RPC, as a takeover writes them: no clear
  rpc ikev2profile/ppk-rpc "crypto ikev2 profile CLASSICAL-PROFILE
 keyring ppk CLASSICAL-KEYRING
 exit
event manager environment $var \"$(sha8 CLASSICAL-KEYRING) $place CLASSICAL-KEYRING\""
  record ikev2profile/ppk-mark-applied "$eem=$var"
  write PUT "$eem=$var" "$(jq -nc --arg n "$var" --arg v "$(sha8 OLD-KEYRING) $place OLD-KEYRING" \
    '{"Cisco-IOS-XE-eem:environment": [{name: $n, value: $v}]}')"
  record ikev2profile/ppk-mark-other "$eem=$var"
  write DELETE "$eem=$var"

  put 'del(.match.identity.remote.address.ipv4[0]["ipv4-mask"])'
  put 'del(.match.identity.remote.address.ipv4[0]["ipv4-mask"])'
  record ikev2profile/profile-no-mask "$url"
  put '.match.identity.remote.address.ipv4 = [{"ipv4-address": "10.0.12.9", "ipv4-mask": "255.255.255.255"}]'
  record ikev2profile/profile-other-address "$url"
  put '.match.identity.remote.address.ipv4 += [{"ipv4-address": "10.0.12.2", "ipv4-mask": "255.255.255.255"}]'
  record ikev2profile/profile-extra-address "$url"
  # Manage's write over another address and a description made by hand: a merge adds
  # the spec's address and keeps both
  put '.match.identity.remote.address.ipv4 = [{"ipv4-address": "10.0.12.9", "ipv4-mask": "255.255.255.255"}]
    | .description = "made by hand"'
  patch ikev2profile/profile-patch \
    "$(jq -nc --argjson p "$example" '{"Cisco-IOS-XE-native:native": {crypto: {"Cisco-IOS-XE-crypto:ikev2": {profile: [$p]}}}}')"
  record ikev2profile/profile-patched "$url"

  write DELETE "$url"
  write DELETE "$keyring"
}

ipsectransformset() { # iosxe/examples/ipsectransformset/r1.yaml
  local url=$NATIVE/crypto/Cisco-IOS-XE-crypto:ipsec/transform-set=CLASSICAL-TS
  local example='{"tag": "CLASSICAL-TS", "esp": "esp-gcm", "key-bit": "256", "mode": {"tunnel-choice": [null]}}'
  put() { # put <jq update of the example>: one field differs per state
    write PUT "$url" "$(jq -nc --argjson t "$example" "{\"Cisco-IOS-XE-crypto:transform-set\": [\$t | $1]}")"
  }
  absent "$url"
  record ipsectransformset/transform-set-absent "$url"

  put .
  record ipsectransformset/transform-set-applied "$url"
  put 'del(.["key-bit"])'
  record ipsectransformset/transform-set-key-bit-128 "$url"
  put '.mode = {"transport-choice": {}}'
  record ipsectransformset/transform-set-transport "$url"
  put '.esp = "esp-aes" | .["esp-hmac"] = "esp-sha256-hmac"'
  record ipsectransformset/transform-set-aes-with-hmac "$url"
  # Manage's write over a block that differs in every field: the router drops esp-hmac
  # itself when esp becomes esp-gcm
  put '.esp = "esp-aes" | .["key-bit"] = "192" | .["esp-hmac"] = "esp-sha256-hmac" | .mode = {"transport-choice": {}}'
  patch ipsectransformset/transform-set-patch \
    "$(jq -nc --argjson t "$example" '{"Cisco-IOS-XE-native:native": {crypto: {"Cisco-IOS-XE-crypto:ipsec": {"transform-set": [$t]}}}}')"
  record ipsectransformset/transform-set-patched "$url"
  # a key length of 128, the router's default, named in the merge to replace 256
  patch ipsectransformset/transform-set-patch-key-bit-128 \
    "$(jq -nc --argjson t "$example" '{"Cisco-IOS-XE-native:native": {crypto: {"Cisco-IOS-XE-crypto:ipsec": {"transform-set": [$t | .["key-bit"] = "128"]}}}}')"
  record ipsectransformset/transform-set-patched-key-bit-128 "$url"

  write DELETE "$url"
}

ipsecprofile() { # iosxe/examples/ipsecprofile/r1.yaml, on transform-sets and an IKEv2 profile
  local url=$NATIVE/crypto/Cisco-IOS-XE-crypto:ipsec/profile=CLASSICAL-IPSEC
  local ts=$NATIVE/crypto/Cisco-IOS-XE-crypto:ipsec/transform-set
  local keyring=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/keyring=CLASSICAL-KEYRING
  local profile=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/profile=CLASSICAL-PROFILE
  local example='{"name": "CLASSICAL-IPSEC", "set": {"transform-set": ["CLASSICAL-TS"], "ikev2-profile": "CLASSICAL-PROFILE"}}'
  put() { # put <jq update of the example>: one field differs per state
    write PUT "$url" "$(jq -nc --argjson p "$example" "{\"Cisco-IOS-XE-crypto:profile\": [\$p | $1]}")"
  }
  absent "$url"
  record ipsecprofile/profile-absent "$url"

  for tag in CLASSICAL-TS OTHER-TS; do
    write PUT "$ts=$tag" "{\"Cisco-IOS-XE-crypto:transform-set\": [{\"tag\": \"$tag\", \"esp\": \"esp-gcm\",
      \"key-bit\": \"256\", \"mode\": {\"tunnel-choice\": [null]}}]}"
  done
  write PUT "$keyring" "$(jq -nc --arg psk "$PSK" '{"Cisco-IOS-XE-crypto:keyring": [{name: "CLASSICAL-KEYRING", peer: [{name: "R3",
    address: {ipv4: {"ipv4-address": "10.0.23.2"}}, "pre-shared-key": {key: $psk}}]}]}')"
  write PUT "$profile" '{"Cisco-IOS-XE-crypto:profile": [{"name": "CLASSICAL-PROFILE",
    "authentication": {"local": {"pre-share": {}}, "remote": {"pre-share": {}}},
    "keyring": {"local": {"name": "CLASSICAL-KEYRING"}},
    "match": {"identity": {"remote": {"address": {"ipv4": [{"ipv4-address": "10.0.23.2", "ipv4-mask": "255.255.255.255"}]}}}}}]}'
  put .
  record ipsecprofile/profile-applied "$url"
  put '.set["transform-set"] = ["OTHER-TS", "CLASSICAL-TS"]'
  record ipsecprofile/profile-extra-transform-set "$url"
  put '.set["transform-set"] = ["OTHER-TS"]'
  record ipsecprofile/profile-other-transform-set "$url"
  put 'del(.set["ikev2-profile"])'
  record ipsecprofile/profile-no-ikev2-profile "$url"
  put '.set.pfs = {"group": "group20"}'
  record ipsecprofile/profile-with-pfs "$url"
  # Manage's write over OTHER-TS alone and no IKEv2 profile: a merge keeps OTHER-TS
  put '.set = {"transform-set": ["OTHER-TS"]}'
  patch ipsecprofile/profile-patch \
    "$(jq -nc --argjson p "$example" '{"Cisco-IOS-XE-native:native": {crypto: {"Cisco-IOS-XE-crypto:ipsec": {profile: [$p]}}}}')"
  record ipsecprofile/profile-patched "$url"

  write DELETE "$url"
  write DELETE "$profile"
  write DELETE "$keyring"
  for tag in CLASSICAL-TS OTHER-TS; do write DELETE "$ts=$tag"; done
}

tunnelinterface() { # iosxe/examples/tunnelinterface/r1.yaml, on part 9's IPsec profile
  local url=$NATIVE/interface/Tunnel=0
  local oper=$BASE/data/Cisco-IOS-XE-interfaces-oper:interfaces/interface=Tunnel0/oper-status
  local sa="$BASE/data/Cisco-IOS-XE-crypto-oper:crypto-oper-data/crypto-ikev2-sa?fields=sa-data(sa-status;remote-ip-addr)"
  local example='{"name": 0, "ip": {"address": {"primary": {"address": "192.168.100.1", "mask": "255.255.255.0"}}},
    "Cisco-IOS-XE-tunnel:tunnel": {"source": "GigabitEthernet2", "destination-config": {"ipv4": "10.0.23.2"},
    "mode": {"ipsec": {"ipv4-mode": {}, "ipv4": {}}},
    "protection": {"Cisco-IOS-XE-crypto:ipsec": {"profile-option": {"name": "CLASSICAL-IPSEC"}}}}}'
  put() { # put <jq update of the example>: one field differs per state
    write PUT "$url" "$(jq -nc --argjson t "$example" "{\"Cisco-IOS-XE-native:Tunnel\": [\$t | $1]}")"
  }
  stack() { # stack <native url> <peer name> <peer address>: the IPsec profile and what it names
    local crypto=$1/crypto/Cisco-IOS-XE-crypto
    write PUT "$crypto:ipsec/transform-set=CLASSICAL-TS" '{"Cisco-IOS-XE-crypto:transform-set": [{"tag": "CLASSICAL-TS",
      "esp": "esp-gcm", "key-bit": "256", "mode": {"tunnel-choice": [null]}}]}'
    write PUT "$crypto:ikev2/keyring=CLASSICAL-KEYRING" "$(jq -nc --arg psk "$PSK" --arg n "$2" --arg a "$3" \
      '{"Cisco-IOS-XE-crypto:keyring": [{name: "CLASSICAL-KEYRING",
      peer: [{name: $n, address: {ipv4: {"ipv4-address": $a}}, "pre-shared-key": {key: $psk}}]}]}')"
    write PUT "$crypto:ikev2/profile=CLASSICAL-PROFILE" "$(jq -nc --arg a "$3" '{"Cisco-IOS-XE-crypto:profile": [{name: "CLASSICAL-PROFILE",
      authentication: {local: {"pre-share": {}}, remote: {"pre-share": {}}},
      keyring: {local: {name: "CLASSICAL-KEYRING"}},
      match: {identity: {remote: {address: {ipv4: [{"ipv4-address": $a, "ipv4-mask": "255.255.255.255"}]}}}}}]}')"
    write PUT "$crypto:ipsec/profile=CLASSICAL-IPSEC" '{"Cisco-IOS-XE-crypto:profile": [{"name": "CLASSICAL-IPSEC",
      "set": {"transform-set": ["CLASSICAL-TS"], "ikev2-profile": "CLASSICAL-PROFILE"}}]}'
  }
  unstack() { # unstack <native url>
    local crypto=$1/crypto/Cisco-IOS-XE-crypto
    write DELETE "$crypto:ipsec/profile=CLASSICAL-IPSEC"
    write DELETE "$crypto:ikev2/profile=CLASSICAL-PROFILE"
    write DELETE "$crypto:ikev2/keyring=CLASSICAL-KEYRING"
    write DELETE "$crypto:ipsec/transform-set=CLASSICAL-TS"
  }
  sa_is() { # sa_is <state>: the SA to 10.0.23.2 is in it
    curl_ "$sa" | jq -e --arg s "crypto-sa-status-$1" \
      '[.["Cisco-IOS-XE-crypto-oper:crypto-ikev2-sa"][]?["sa-data"] | select(.["remote-ip-addr"] == "10.0.23.2")
        | .["sa-status"]] | index($s) != null' > /dev/null
  }
  oper_is() { # oper_is <state>: Tunnel0's oper-status
    curl_ "$oper" | jq -e --arg s "if-oper-state-$1" '.["Cisco-IOS-XE-interfaces-oper:oper-status"] == $s' > /dev/null
  }
  : "${PEER:?the router at 10.0.23.2, for the state of the tunnel}"
  local peer=https://$PEER/restconf/data/Cisco-IOS-XE-native:native
  absent "$url"
  record tunnelinterface/tunnel-absent "$url"
  record tunnelinterface/oper-absent "$oper"
  record tunnelinterface/sa-none "$sa"

  stack "$NATIVE" R3 10.0.23.2
  put .
  record tunnelinterface/tunnel-applied "$url"
  until_ "lower-layer-down" oper_is lower-layer-down
  until_ "pending" sa_is pending
  record tunnelinterface/oper-lower-layer-down "$oper"
  record tunnelinterface/sa-pending "$sa"

  onpeer stack "$peer" R1 10.0.12.1
  onpeer write PUT "$peer/interface/Tunnel=0" '{"Cisco-IOS-XE-native:Tunnel": [{"name": 0,
    "ip": {"address": {"primary": {"address": "192.168.100.2", "mask": "255.255.255.0"}}},
    "Cisco-IOS-XE-tunnel:tunnel": {"source": "GigabitEthernet2", "destination-config": {"ipv4": "10.0.12.1"},
    "mode": {"ipsec": {"ipv4-mode": {}, "ipv4": {}}},
    "protection": {"Cisco-IOS-XE-crypto:ipsec": {"profile-option": {"name": "CLASSICAL-IPSEC"}}}}}]}'
  until_ "ready" oper_is ready
  until_ "active" sa_is active
  record tunnelinterface/oper-ready "$oper"
  record tunnelinterface/sa-active "$sa"
  onpeer write DELETE "$peer/interface/Tunnel=0"
  onpeer unstack "$peer"

  put '.ip.address.primary.mask = "255.255.255.255"'
  record tunnelinterface/tunnel-host-mask "$url"
  put '.["Cisco-IOS-XE-tunnel:tunnel"]["destination-config"].ipv4 = "10.0.23.9"'
  record tunnelinterface/tunnel-other-destination "$url"
  put 'del(.["Cisco-IOS-XE-tunnel:tunnel"].mode)'
  record tunnelinterface/tunnel-gre "$url"
  put 'del(.["Cisco-IOS-XE-tunnel:tunnel"].protection)'
  record tunnelinterface/tunnel-no-protection "$url"
  put '.shutdown = [null]'
  record tunnelinterface/tunnel-shutdown "$url"
  # Manage's write over another destination and mask, and a description made by hand:
  # a merge puts back the spec's and keeps the description
  put '.ip.address.primary.mask = "255.255.255.255" | .description = "made by hand"
    | .["Cisco-IOS-XE-tunnel:tunnel"]["destination-config"].ipv4 = "10.0.23.9"'
  patch tunnelinterface/tunnel-patch \
    "$(jq -nc --argjson t "$example" '{"Cisco-IOS-XE-native:native": {interface: {Tunnel: [$t]}}}')"
  record tunnelinterface/tunnel-patched "$url"

  write DELETE "$url"
  unstack "$NATIVE"
}

mkdir -p "$FIXTURES"
jq -n --arg psk "$PSK" --arg ppk "$PPK_HEX" \
  '{"ike-keys": {psk: $psk, "ppk-hex": $ppk}}' > "$FIXTURES/secrets.json"

for kind in "${KINDS[@]}"; do
  if [ $# -eq 0 ] || printf '%s\n' "$@" | grep -qx "$kind"; then "$kind"; fi
done
