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
# 0.5.11 is a floor, not a preference: below it cEOS RESTCONF either never came
# up on 6020, or came up and did not survive a container restart. This lab is
# expected to outlive a laptop going to sleep.
# renovate: datasource=helm depName=netclab registryUrl=https://netclab.github.io/netclab-chart
NETCLAB_CHART=${NETCLAB_CHART:-0.5.11}
CEOS_IMG=${CEOS_IMG:-localhost:${REG_PORT}/netclab/ceos:4.36.1F}
TOPO=${TOPO:-${HERE}/topology.yaml}

# The fabric scenario runs on its own devices, named by the AVD model
# (dc1-spine1, dc1-leaf1a) rather than ceos01/ceos02. Opt-in, because it is two
# more cEOS pods that the other four scenarios never touch, and because a push
# replaces a device's whole config -- which would take netclab-chart's RESTCONF
# bootstrap with it, since AVD renders no RESTCONF.
WITH_FABRIC=${WITH_FABRIC:-0}
# The design and the topology are fetched from the SAME tag on purpose. AVD
# resolves the cabling, so the topology is derived from the model rather than
# written by hand -- but only for the AVD version that derived it. Pinning both
# to one ref is what stops `spec.push.hosts` and the running devices from
# drifting apart; a push to a device that is not running never converges.
# Keep this in step with the ref in scenarios/fabric/kustomization.yaml.
AVD_REF=${AVD_REF:-v0.1.6}
# Which matched pair to use. Upstream keeps the push-hosts kustomization and
# the topology for a subset in one directory, so this single name selects both.
AVD_LAB=${AVD_LAB:-lab}
# One topology per namespace is netclab-chart's documented model, and the
# Fabric has to share it: function-avd derives each device URL from the XR's
# own namespace. Keep in step with scenarios/fabric/.
AVD_NS=${AVD_NS:-avd}
AVD_TOPO_URL=${AVD_TOPO_URL:-https://raw.githubusercontent.com/netclab/function-avd/${AVD_REF}/examples/${AVD_LAB}/topology.yaml}

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
# Same invocation as the workflows'. The package root is `apis/`, which is why
# there is no --ignore: this script's own topology.yaml is helm values with no
# `kind`, and with the repo root as package root it had to be excluded by name.
crossplane xpkg build \
  --package-root=apis \
  --examples-root=./examples \
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

if [ "$WITH_FABRIC" = "1" ]; then
  # A second release in a namespace of its own, which is netclab-chart's
  # documented model -- its README installs several topologies that way, and
  # objects like `ceos-startup-config` and `delay-job` carry fixed names that
  # only the namespace boundary keeps apart. Two topologies in one namespace
  # would collide on them.
  #
  # It also keeps the two independent: this topology is generated from the AVD
  # model, the other is hand-written, and they are meant to evolve separately.
  echo ">> AVD lab topology from function-avd ${AVD_REF} (${AVD_LAB})"
  AVD_TOPO="$(mktemp -t avd-topology.XXXXXX.yaml)"
  trap 'rm -f "$AVD_TOPO"' EXIT
  # --fail, because curl exits 0 on a 404 and a missing ref would otherwise
  # reach helm as an empty values file and install nothing, quietly.
  if ! curl -sfL "$AVD_TOPO_URL" -o "$AVD_TOPO"; then
    echo "!! cannot fetch ${AVD_TOPO_URL}"
    echo "   Does examples/${AVD_LAB}/topology.yaml exist at ref ${AVD_REF}?"
    exit 1
  fi
  # Upstream generates the topology with a plain `ceos:<tag>`, which is what
  # `docker import` + `kind load` leaves and what the documentation describes.
  # This script serves cEOS from the local registry instead -- it survives
  # teardown -- so point the copy at it. The tag still comes from the topology:
  # it is generated from the AVD model, so the model picks the EOS version.
  AVD_CEOS_TAG="$(awk '/image:/ {print $2; exit}' "$AVD_TOPO")"
  sed -i "s|^\( *image: \).*|\1${CEOS_IMG%:*}:${AVD_CEOS_TAG##*:}|" "$AVD_TOPO"

  echo ">> netclab-chart ${NETCLAB_CHART} (AVD devices in ${AVD_NS})"
  helm upgrade --install avd netclab/netclab --version "${NETCLAB_CHART}" \
    --kube-context "$CTX" -n "$AVD_NS" --create-namespace -f "$AVD_TOPO" >/dev/null
fi

echo
# There is no readiness object to wait on. netclab-chart 0.5.11 dropped the
# certificate Job -- RESTCONF now comes up from the startup-config alone -- and
# a cEOS pod reports Running well before EOS has finished booting. So the only
# honest signal is the device answering.
echo "cEOS takes ~2min to boot. Ready when both devices answer:"
echo "  for n in ceos01 ceos02; do kubectl --context ${CTX} -n default exec \$n -- \\"
echo "    Cli -p 15 -c 'show management api restconf' | head -2; done"
echo "  kubectl --context ${CTX} apply -k ${ROOT}/scenarios/prerequisites"
if [ "$WITH_FABRIC" = "1" ]; then
  echo
  echo "The AVD devices boot alongside them; the fabric scenario needs its own"
  echo "prerequisites, and its push replaces those devices' whole config:"
  echo "  kubectl --context ${CTX} apply -k ${ROOT}/scenarios/fabric/prerequisites"
  echo "  kubectl --context ${CTX} apply -k ${ROOT}/scenarios/fabric"
fi
