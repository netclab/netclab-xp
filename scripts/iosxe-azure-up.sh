#!/usr/bin/env bash
# Bring up Catalyst 8000V routers in an existing Azure resource group, with
# RESTCONF reachable from this machine. Idempotent; safe to re-run.
#
# All routers share one subnet and have one NIC each. A hub-and-spoke overlay
# needs nothing more: the hub sources every tunnel from the same interface.
set -euo pipefail

: "${AZ_RG:?set AZ_RG to the resource group}"
: "${IOSXE_USER:?set IOSXE_USER}"
: "${IOSXE_PASSWORD:?set IOSXE_PASSWORD}"
# The image lives in the environment, not here, so moving to a newer release
# is a change of one variable. List them with:
#   az vm image list --publisher cisco --offer cisco-c8000v-payg --all -o table
: "${IOSXE_IMAGE:?set IOSXE_IMAGE, e.g. cisco:cisco-c8000v-payg:26_02_payg-advantage:26.02.010}"

IOSXE_VM=${IOSXE_VM:-r1}
IOSXE_SIZE=${IOSXE_SIZE:-Standard_DS1_v2}
if [ -z "${AZ:-}" ]; then
  if command -v az >/dev/null; then AZ=az; else AZ="uvx --from azure-cli az"; fi
fi
VNET=iosxe-vnet
SUBNET=iosxe-snet
NSG=iosxe-nsg

if [ -z "${ALLOW_FROM:-}" ]; then
  ALLOW_FROM="$(curl -sf https://api.ipify.org)/32"
fi

LOCATION="$($AZ group show -n "$AZ_RG" --query location -o tsv)"
echo ">> resource group ${AZ_RG} (${LOCATION}), routers: ${IOSXE_VM}"

echo ">> network: ${VNET}/${SUBNET}, ${NSG} (22, 443 from ${ALLOW_FROM})"
# Created before the routers, so parallel VM creation does not race for them.
$AZ network vnet create -g "$AZ_RG" -l "$LOCATION" -n "$VNET" \
  --address-prefixes 10.0.0.0/16 \
  --subnet-name "$SUBNET" --subnet-prefixes 10.0.123.0/24 -o none
$AZ network nsg create -g "$AZ_RG" -l "$LOCATION" -n "$NSG" -o none
$AZ network nsg rule create -g "$AZ_RG" --nsg-name "$NSG" -n ssh --priority 1010 \
  --source-address-prefixes "$ALLOW_FROM" --destination-port-ranges 22 \
  --protocol Tcp --access Allow -o none
$AZ network nsg rule create -g "$AZ_RG" --nsg-name "$NSG" -n restconf --priority 1020 \
  --source-address-prefixes "$ALLOW_FROM" --destination-port-ranges 443 \
  --protocol Tcp --access Allow -o none

# Once per subscription.
echo ">> accept the image's marketplace terms"
if ! $AZ vm image terms accept --urn "$IOSXE_IMAGE" -o none 2>/dev/null; then
  echo "   could not accept them; creating a VM fails unless already accepted"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for vm in $IOSXE_VM; do
  if $AZ vm show -g "$AZ_RG" -n "$vm" -o none 2>/dev/null; then
    echo ">> ${vm}: exists"
    continue
  fi
  # Day-0 configuration in the format of Cisco's Azure deployment guide. What
  # the factory configuration lacks for RESTCONF is `ip http authentication
  # local` and `restconf` itself.
  cat >"$TMP/${vm}.txt" <<EOF
Section: IOS configuration
  hostname ${vm}
  ip http secure-server
  ip http authentication local
  restconf
EOF
  echo ">> ${vm}: create"
  $AZ vm create -g "$AZ_RG" -l "$LOCATION" -n "$vm" \
    --image "$IOSXE_IMAGE" --size "$IOSXE_SIZE" \
    --admin-username "$IOSXE_USER" --admin-password "$IOSXE_PASSWORD" \
    --authentication-type password \
    --vnet-name "$VNET" --subnet "$SUBNET" --nsg "$NSG" \
    --public-ip-address "${vm}-ip" --public-ip-sku Standard \
    --custom-data "$TMP/${vm}.txt" --no-wait -o none
done

for vm in $IOSXE_VM; do
  $AZ vm wait -g "$AZ_RG" -n "$vm" --created
  # Managed storage; gives the serial console in the portal.
  $AZ vm boot-diagnostics enable -g "$AZ_RG" -n "$vm" -o none
done

echo ">> waiting for RESTCONF (IOS XE boots, then RESTCONF takes minutes more)"
# The password goes to curl on stdin, not on its command line.
for vm in $IOSXE_VM; do
  ip="$($AZ vm show -d -g "$AZ_RG" -n "$vm" --query publicIps -o tsv)"
  deadline=$((SECONDS + 1200))
  until code="$(printf 'user = "%s:%s"\n' "$IOSXE_USER" "$IOSXE_PASSWORD" \
      | curl -sk -K - -m 10 -o /dev/null -w '%{http_code}' \
          -H 'Accept: application/yang-data+json' \
          "https://${ip}/restconf/data/Cisco-IOS-XE-native:native/hostname")" \
      && [ "$code" = 200 ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      echo "!! ${vm} (${ip}): RESTCONF not up after 20 min, last HTTP ${code:-none}"
      exit 1
    fi
    sleep 15
  done
  echo "   ${vm}: RESTCONF up at https://${ip}"
done

echo
$AZ vm list-ip-addresses -g "$AZ_RG" -o table
