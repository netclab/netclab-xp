# Install the package

## Crossplane

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace
```

## The Configuration

Pick a version from the
[tags](https://github.com/netclab/netclab-xp/tags) named `eos/v*`. The git tag
*is* the package version, so the two can never disagree.

```bash
VERSION=<version>   # the newest eos/v* tag, without eos/

cat <<EOF | kubectl apply -f -
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: configuration-eos
spec:
  package: xpkg.upbound.io/netclab/configuration-eos:${VERSION}
EOF
```

Until `v0.5.0` the package was published as `netclab-xp`, tagged `v*`.

`dependsOn` pulls in provider-http and the functions the compositions need, so
there is nothing else to install by hand. Wait for it to settle:

```bash
kubectl wait --for=condition=Healthy configuration.pkg.crossplane.io/configuration-eos --timeout=300s
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

kubectl apply -k eos/scenarios/prerequisites
```

All three are cluster-wide — the `ClusterProviderConfig` and `EnvironmentConfig`
are cluster scoped, and the `Secret` belongs to `crossplane-system` because the
compositions name it there. So this is a one-time step no matter which namespace
you later put resources in.

That is everything. Next, apply
[your first resource](first-resource.md) — one at a time, watching what each
does to a device — or go straight to a [scenario](scenarios/index.md), which
applies a whole set at once.
