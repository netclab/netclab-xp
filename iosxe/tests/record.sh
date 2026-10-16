#!/bin/bash
# Records the router's answers to the GETs the compositions observe with, in each state
# the objects of iosxe/examples/ can be in.
#
#   iosxe/tests/record.sh <router-address> <ios-xe-version> [kind...]
#
# Writes iosxe/tests/fixtures/<ios-xe-version>/<kind>/, and secrets.json with the values
# the router held, which the tests put in place of {{ name:namespace:key }}. Kinds run in
# apply order, all of them when none is named. Leaves nothing behind on the router.
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
KINDS=(ikev2proposal ikev2policy ikev2keyring ikev2profile)

# the values the examples' Secrets hold
PSK=TestPsk123
PPK_HEX=48656C6C6F506F737451756172746E756D   # "HelloPostQuartnum"

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

  write DELETE "$url"
  write DELETE "$proposal"
}

ikev2keyring() { # iosxe/examples/ikev2keyring/r1.yaml
  local url=$NATIVE/crypto/Cisco-IOS-XE-crypto:ikev2/keyring=CLASSICAL-KEYRING
  local body
  body() {
    jq -nc --arg psk "$1" '{"Cisco-IOS-XE-crypto:keyring": [{name: "CLASSICAL-KEYRING", peer: [{name: "R3",
      address: {ipv4: {"ipv4-address": "10.0.23.2"}}, "pre-shared-key": {key: $psk}}]}]}'
  }
  absent "$url"
  record ikev2keyring/keyring-absent "$url"
  record ikev2keyring/peer-absent "$url/peer=R3"

  write PUT "$url" "$(body "$PSK")"
  record ikev2keyring/keyring-unmarked "$url"
  record ikev2keyring/peer-unmarked "$url/peer=R3"

  cli "crypto ikev2 keyring CLASSICAL-KEYRING
 peer R3
  ppk manual id PPK-R1R3 key hex $PPK_HEX required
  description ppk PPK-R1R3"
  record ikev2keyring/keyring-applied "$url"
  record ikev2keyring/peer-marked "$url/peer=R3"

  cli "crypto ikev2 keyring CLASSICAL-KEYRING
 peer R3
  description ppk PPK-OLD"
  record ikev2keyring/peer-old-mark "$url/peer=R3"

  write PUT "$url" "$(body OtherPsk456)"
  record ikev2keyring/keyring-other-psk "$url"

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

  cli "crypto ikev2 profile CLASSICAL-PROFILE
 keyring ppk CLASSICAL-KEYRING
 description ppk CLASSICAL-KEYRING"
  record ikev2profile/profile-marked "$url"
  cli "crypto ikev2 profile CLASSICAL-PROFILE
 description ppk OLD-KR"
  record ikev2profile/profile-old-mark "$url"

  put 'del(.match.identity.remote.address.ipv4[0]["ipv4-mask"])'
  put 'del(.match.identity.remote.address.ipv4[0]["ipv4-mask"])'
  record ikev2profile/profile-no-mask "$url"
  put '.match.identity.remote.address.ipv4 = [{"ipv4-address": "10.0.12.9", "ipv4-mask": "255.255.255.255"}]'
  record ikev2profile/profile-other-address "$url"
  put '.match.identity.remote.address.ipv4 += [{"ipv4-address": "10.0.12.2", "ipv4-mask": "255.255.255.255"}]'
  record ikev2profile/profile-extra-address "$url"

  write DELETE "$url"
  write DELETE "$keyring"
}

mkdir -p "$FIXTURES"
jq -n --arg psk "$PSK" --arg ppk "$PPK_HEX" \
  '{"ike-keys": {psk: $psk, "ppk-hex": $ppk}}' > "$FIXTURES/secrets.json"

for kind in "${KINDS[@]}"; do
  if [ $# -eq 0 ] || printf '%s\n' "$@" | grep -qx "$kind"; then "$kind"; fi
done
