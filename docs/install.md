# Install the package

## Crossplane

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace
```

Tested against Crossplane 2.3.4.

## The Configuration

Pick a version from the
[tags](https://github.com/netclab/netclab-xp/tags). The git tag *is* the package
version, so the two can never disagree.

```bash
VERSION=<version>   # e.g. the newest tag

cat <<EOF | kubectl apply -f -
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: netclab-xp
spec:
  package: xpkg.upbound.io/netclab/netclab-xp:${VERSION}
EOF
```

`dependsOn` pulls in provider-http and the functions the compositions need, so
there is nothing else to install by hand. Wait for it to settle:

```bash
kubectl wait --for=condition=Healthy configuration.pkg.crossplane.io/netclab-xp --timeout=300s
kubectl wait --for=condition=Healthy providers.pkg.crossplane.io --all --timeout=300s
kubectl wait --for=condition=Healthy function.pkg.crossplane.io --all --timeout=300s
```

## Prerequisites

Dependencies are installed for you; the objects the compositions reference *by
name* are not. Those are a `ClusterProviderConfig`, an `EnvironmentConfig`
describing how each protocol is reached, and a `Secret` holding device
credentials.

They live in the repository, so clone it — this is the first step that needs
[git](https://git-scm.com/downloads):

```bash
git clone https://github.com/netclab/netclab-xp
cd netclab-xp

kubectl apply -k scenarios/prerequisites
```

All three are cluster-wide — the `ClusterProviderConfig` and `EnvironmentConfig`
are cluster scoped, and the `Secret` belongs to `crossplane-system` because the
compositions name it there. So this is a one-time step no matter which namespace
you later put resources in.

That is everything. Next, apply
[your first resource](first-resource.md) — one at a time, watching what each
does to a device — or go straight to a [scenario](scenarios/index.md), which
applies a whole set at once.

## Upgrading from 0.2.x

Two hazards, both measured rather than feared.

### `spec.scope` is immutable, so there is no in-place upgrade

0.3.0 moved every resource type from `scope: Cluster` to `scope: Namespaced`.
Pointing an installed Configuration at it fails — the new revision cannot apply
its own definitions:

```console
spec.scope: Invalid value: "Namespaced": Value is immutable
```

The old definitions have to be deleted first. **Deleting a definition deletes
every resource of that kind, and those resources own the requests that
configured your devices — so a plain delete asks provider-http to remove that
configuration from the devices themselves.**

On a lab that is fine. Anywhere else, pause or detach the resources before
removing the Configuration.

There is no migration path by design: cluster-scoped and namespaced resources
are different objects, so configuration is re-created in a namespace after the
upgrade rather than moved.

### A raised dependency floor does not upgrade itself

0.3.0 also raised the `function-eapi` floor to `>=v0.0.23`. Crossplane installs
dependencies that are missing; it does **not** upgrade ones already present. So
the new revision goes `Active` and simply never becomes healthy:

```console
cannot resolve package dependencies: incompatible dependencies: existing
package xpkg.upbound.io/netclab/function-eapi@v0.0.22 is incompatible with
constraint >=v0.0.23
```

Nothing breaks loudly — the resource definitions keep serving — so the symptom
is quiet. Move the dependency yourself:

```bash
kubectl patch function.pkg.crossplane.io netclab-function-eapi --type=merge \
  -p '{"spec":{"package":"xpkg.upbound.io/netclab/function-eapi:v0.0.23"}}'
```
