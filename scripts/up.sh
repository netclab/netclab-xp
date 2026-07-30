#!/usr/bin/env bash
# Bring up a local lab for the scenarios: registry -> kind -> Crossplane ->
# the netclab-xp package built from THIS working tree -> Multus -> two cEOS
# nodes. Idempotent; safe to re-run.
#
# The package is built and pushed rather than applied from apis/, so what the
# cluster runs is the real xpkg -- dependency resolution included. That is the
# point: `kubectl apply -f apis/` would test the manifests, not the package.
#
# Modelled on function-avd/scripts/kind-up.sh, which encodes the hurdle this
# also hits: an image must be pullable by the node's containerd over plain
# HTTP, so the registry is referenced by its kind-network IP and marked
# insecure. Crossplane falls back to HTTP for that registry by itself.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"

CLUSTER=${CLUSTER:-xp3}
CTX="kind-${CLUSTER}"
REG=kind-registry
REG_PORT=5001
# Named volume so the registry outlives the container. cEOS is licensed and
# cannot be pulled, so this is what stops every teardown from costing an import.
REG_VOL=${REG_VOL:-kind-registry-data}
# A moved tag is not re-resolved: `packagePullPolicy` will not notice that
# `:dev` now means something else. Rebuilding means a NEW tag.
TAG=${TAG:-dev}

# renovate: datasource=helm depName=crossplane registryUrl=https://charts.crossplane.io/stable
XP_CHART=${XP_CHART:-2.3.4}
# renovate: datasource=github-releases depName=containernetworking/plugins
CNI_PLUGINS=${CNI_PLUGINS:-v1.9.1}
# renovate: datasource=github-releases depName=k8snetworkplumbingwg/multus-cni
MULTUS=${MULTUS:-v4.3.0}
# 0.5.10 is a floor, not a preference: before it the cEOS RESTCONF SSL profile
# stayed invalid after the certificate Job ran, so nothing ever listened on
# 6020 and every restconf scenario failed to connect.
# renovate: datasource=helm depName=netclab registryUrl=https://netclab.github.io/netclab-chart
NETCLAB_CHART=${NETCLAB_CHART:-0.5.10}
CEOS_IMG=${CEOS_IMG:-localhost:${REG_PORT}/netclab/ceos:4.36.1F}
TOPO=${TOPO:-${HERE}/topology.yaml}

echo ">> local registry (data volume: ${REG_VOL})"
if [ -z "$(docker ps -q -f name="^${REG}$")" ]; then
  docker run -d --restart=always -p "127.0.0.1:${REG_PORT}:5000" \
    -v "${REG_VOL}:/var/lib/registry" --name "$REG" registry:2 >/dev/null
fi
CEOS_REPO="${CEOS_IMG#*/}"; CEOS_REPO="${CEOS_REPO%:*}"
CEOS_TAG="${CEOS_IMG##*:}"
if ! curl -sf "http://localhost:${REG_PORT}/v2/${CEOS_REPO}/tags/list" | grep -q "\"${CEOS_TAG}\""; then
  echo "!! ${CEOS_IMG} is not in the local registry. Import it once:"
  echo "     docker tag ceos:${CEOS_TAG} ${CEOS_IMG} && docker push ${CEOS_IMG}"
  exit 1
fi

echo ">> kind cluster ${CLUSTER}"
if ! kind get clusters | grep -qx "$CLUSTER"; then
  cat <<EOF | kind create cluster --name "$CLUSTER" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry]
    config_path = "/etc/containerd/certs.d"
EOF
fi
docker network connect kind "$REG" 2>/dev/null || true
REG_IP="$(docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' "$REG")"
echo "   registry kind-network IP: ${REG_IP}"

echo ">> containerd: trust the registry over plain HTTP"
for node in $(kind get nodes --name "$CLUSTER"); do
  for host in "localhost:${REG_PORT}" "${REG_IP}:5000"; do
    docker exec "$node" mkdir -p "/etc/containerd/certs.d/${host}"
    printf '[host."http://%s:5000"]\n  capabilities = ["pull", "resolve"]\n' "$REG" \
      | docker exec -i "$node" cp /dev/stdin "/etc/containerd/certs.d/${host}/hosts.toml"
  done
done

echo ">> build + push netclab-xp package (tag ${TAG})"
cd "$ROOT"
# The --ignore globs match the workflows'. They are file-only and do not cross
# '/', so a directory of non-package YAML needs one glob per nesting level --
# `scripts/` is such a directory, because topology.yaml is helm values and has
# no `kind`.
crossplane xpkg build \
  --package-root=. \
  --examples-root=./examples \
  --ignore="./.github/*,./.github/*/*,./scenarios/*,./scenarios/*/*,./scripts/*" \
  -o "/tmp/netclab-xp-${TAG}.xpkg"
crossplane xpkg push -f "/tmp/netclab-xp-${TAG}.xpkg" \
  "localhost:${REG_PORT}/netclab/netclab-xp:${TAG}"

echo ">> install Crossplane (chart ${XP_CHART})"
helm repo add crossplane-stable https://charts.crossplane.io/stable >/dev/null 2>&1 || true
helm repo update crossplane-stable >/dev/null
helm upgrade --install crossplane crossplane-stable/crossplane --version "${XP_CHART}" \
  --kube-context "$CTX" --namespace crossplane-system --create-namespace \
  --wait --timeout 5m >/dev/null

echo ">> install the Configuration (dependsOn pulls provider-http + the functions)"
kubectl --context "$CTX" apply -f - <<EOF
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: netclab-xp
spec:
  package: ${REG_IP}:5000/netclab/netclab-xp:${TAG}
  packagePullPolicy: Always
EOF
kubectl --context "$CTX" wait --for=condition=Healthy configuration.pkg.crossplane.io/netclab-xp --timeout=300s
kubectl --context "$CTX" wait --for=condition=Healthy providers.pkg.crossplane.io --all --timeout=300s
kubectl --context "$CTX" wait --for=condition=Healthy function.pkg.crossplane.io --all --timeout=300s

echo ">> netclab-chart prerequisites: CNI plugins ${CNI_PLUGINS} + Multus ${MULTUS}"
for node in $(kind get nodes --name "$CLUSTER"); do
  docker exec "$node" bash -c "curl -sSL \
    https://github.com/containernetworking/plugins/releases/download/${CNI_PLUGINS}/cni-plugins-linux-amd64-${CNI_PLUGINS}.tgz \
    | tar -xz -C /opt/cni/bin ./bridge ./host-device"
done
kubectl --context "$CTX" apply -f \
  "https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/${MULTUS}/deployments/multus-daemonset.yml"
kubectl --context "$CTX" -n kube-system wait --for=jsonpath='{.status.numberReady}'=1 \
  --timeout=5m daemonset.apps/kube-multus-ds

echo ">> netclab-chart ${NETCLAB_CHART} (ceos01, ceos02 in default)"
helm repo add netclab https://netclab.github.io/netclab-chart >/dev/null 2>&1 || true
helm repo update netclab >/dev/null
helm upgrade --install lab netclab/netclab --version "${NETCLAB_CHART}" \
  --kube-context "$CTX" -n default -f "$TOPO" >/dev/null

echo
echo "Ready once the cert Jobs complete (~2min from a cold boot):"
echo "  kubectl --context ${CTX} -n default get jobs -w"
echo "  kubectl --context ${CTX} apply -k ${ROOT}/scenarios/prerequisites"
