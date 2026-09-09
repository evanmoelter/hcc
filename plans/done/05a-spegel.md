# Plan: Add Spegel (P2P container image distribution)

Landed on Apollo at `kubernetes/apollo/apps/kube-system/spegel/`, chart 0.7.4. The
original draft targeted `kubernetes/main` and k3s; the k3s copy was never built,
and the old cluster is frozen, so only the Talos form is recorded here.

## What Spegel does

A stateless cluster-local OCI registry mirror running as a DaemonSet. A node that
needs an image another node already holds pulls it over the LAN instead of from the
external registry, which cuts egress and speeds up pulls after the first one.

## Talos configuration

The chart's containerd defaults already match Talos, except the registry
configuration directory:

| Setting | Talos value | Source |
|---|---|---|
| `containerdSock` | `/run/containerd/containerd.sock` | chart default |
| `containerdContentPath` | `/var/lib/containerd/io.containerd.content.v1.content` | chart default |
| `containerdRegistryConfigPath` | `/etc/cri/conf.d/hosts` | overridden in the HelmRelease |

`service.registry.hostPort` moves from the chart's default 30020 to 29999, with the
reason noted inline in the HelmRelease. The default sits inside Kubernetes' allocatable NodePort range, 30000-32767, which
Apollo does not override, so the API server can hand 30020 to a NodePort service
without knowing a hostPort already holds it. 29999 sits just below the range. Four
of the five community repos surveyed do the same.

Spegel also needs containerd to keep unpacked layers. That is
`discard_unpacked_layers = false` in `bootstrap/talos/all/70-cri.yaml`, which has to
reach the node with the machine config rather than with the chart.

Talos exempts `kube-system` from Pod Security admission, so the DaemonSet's host
mounts need no namespace label there. Deploying Spegel to its own namespace would.

## Deferred

`serviceMonitor.enabled` and `grafanaDashboard.enabled` stay off until
kube-prometheus-stack lands, the next component in the migration plan's Phase B.
The ServiceMonitor cannot be applied before its CRD exists. The dashboard has no such
constraint in its default `Sidecar` mode, which renders a plain ConfigMap; it waits
only because nothing would read it yet. Keep `Sidecar` mode unless Apollo also gets
the Grafana operator, whose mode does need a CRD.

## Values not carried over from community repos

- `spegel.containerdSock`, which every surveyed repo states explicitly even though
  it already matches the chart default on Talos. `containerdContentPath` is equally
  Talos-specific and none of them state it, so the habit looks like inertia.
- `spegel.appendMirrors`, in two repos. The chart dropped the key; 0.7.4 calls the
  equivalent `prependExisting`. Helm ignores unknown values silently, so both repos
  are setting nothing.

## Verification

```sh
kubectl --context apollo -n kube-system get ds spegel
kubectl --context apollo -n kube-system logs -l app.kubernetes.io/name=spegel -c registry
talosctl -n <node> read /etc/cri/conf.d/hosts/_default/hosts.toml
```

`mirroredRegistries` is left empty, which mirrors every registry rather than none, so
Spegel writes a single catch-all `_default/hosts.toml` on each node and no per-registry
file. Its absence means the init container could not reach the registry configuration
path. Do not look for `ghcr.io/hosts.toml`; nothing writes one under this config.
