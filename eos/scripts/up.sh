#!/usr/bin/env bash
# Bring up a local lab for the scenarios with `netclab up`: registry, kind,
# Multus, two cEOS nodes, Crossplane, and the netclab-xp package built from THIS
# working tree. Safe to re-run.
#
# The package is built and pushed rather than applied from apis/, so what the
# cluster runs is the real xpkg -- dependency resolution included.
set -euo pipefail

cd "$(dirname "$0")/.."

CLUSTER=${CLUSTER:-xp}
# A moved tag is not pulled again, so every rebuild needs a new TAG.
TAG=${TAG:?set TAG, a new one on every rebuild}

# The registry first: the package is pushed to it before Crossplane installs it.
uvx netclab up --cluster "$CLUSTER"

crossplane xpkg build --package-root=apis --examples-root=./examples \
  -o "/tmp/netclab-xp-${TAG}.xpkg"
crossplane xpkg push -f "/tmp/netclab-xp-${TAG}.xpkg" "localhost:5001/netclab/netclab-xp:${TAG}"

# Crossplane pulls by the registry's address on the kind network.
REG_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' kind-registry)
uvx netclab up --cluster "$CLUSTER" --crossplane v2.4.3 \
  --configuration "${REG_IP}:5000/netclab/netclab-xp:${TAG}" \
  --namespace default --values scripts/topology.yaml
