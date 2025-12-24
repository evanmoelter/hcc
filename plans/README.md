# Implementation Plans

This directory contains implementation plans for improvements identified from the upstream [onedr0p/cluster-template](https://github.com/onedr0p/cluster-template).

> **Note:** These plans assume you're working directly with generated config files, not maintaining the template system. Template-related improvements have been marked as skipped or simplified accordingly.

## Plan Overview

| # | Plan | Effort | Dependencies | Priority | Status |
|---|------|--------|--------------|----------|--------|
| 01 | [mise Configuration](./01-mise-configuration.md) | 1h | None | High | Active |
| 02 | [Flux Operator](./02-flux-operator.md) | 4-6h | None | Medium | Active |
| 03 | [Helmfile Bootstrap](./03-helmfile-bootstrap.md) | 2h | 01 | Low | Optional |
| 04 | [Envoy Gateway](./04-envoy-gateway.md) | 6-8h | None | Low | Active |
| 05a | [Spegel](./05a-spegel.md) | 1h | None | Medium | Active |
| 05b | [CoreDNS Helm](./05b-coredns-helm.md) | 2-3h | None | Low | Active |
| 05c | [Cloudflare DNS](./05c-cloudflare-dns.md) | 1-2h | None | Medium | Active |
| 06 | [Renovate Improvements](./06-renovate-improvements.md) | 30m | 01 | High | Active |
| 07 | [Flux Local Workflow](./07-flux-local-workflow.md) | 30m | None | High | Active |
| 08 | [HelmRelease Defaults](./08-helmrelease-defaults.md) | 30m | None | High | Active |
| 09 | [Simplified Taskfiles](./09-simplified-taskfiles.md) | 1h | 01 | Medium | Active |

## Recommended Implementation Order

### Quick Wins (< 1 hour each)
1. **07 - Flux Local Workflow** - Better CI/CD
2. **08 - HelmRelease Defaults** - Improved reliability
3. **06 - Renovate Improvements** - Better dependency management

### Foundation (implement together)
4. **01 - mise Configuration** - Developer tooling foundation
5. **09 - Simplified Taskfiles** - Streamlined workflows (no template tasks needed)

### New Components (independent)
6. **05a - Spegel** - P2P image distribution
7. **05c - Cloudflare DNS** - Automatic DNS management

### Larger Changes (plan carefully)
8. **02 - Flux Operator** - Major Flux change

### Optional / Consider Later
9. **03 - Helmfile Bootstrap** - Only useful for rebuilding cluster from scratch
10. **04 - Envoy Gateway** - Major ingress migration
11. **05b - CoreDNS Helm** - Only if you need custom CoreDNS config

## k3s Compatibility Notes

All plans are compatible with k3s. The original template has moved to Talos-only, but the improvements can be adapted for k3s:

- **mise**: ✅ Fully compatible
- **Flux Operator**: ✅ Fully compatible
- **Helmfile**: ✅ Requires k3s-specific values
- **Envoy Gateway**: ✅ Works with k3s
- **Spegel**: ✅ Requires k3s containerd paths
- **CoreDNS**: ⚠️ Must disable k3s built-in
- **Cloudflare DNS**: ✅ Fully compatible
- **Renovate**: ✅ Fully compatible
- **Flux Local**: ✅ Fully compatible
- **HelmRelease Defaults**: ✅ Fully compatible
- **Taskfiles**: ✅ Maintains ansible/k3s support

## Template-Free Workflow

Since you're working with generated configs directly (not maintaining templates):

1. **Edit files directly** in `kubernetes/` and `ansible/`
2. **No need for** `task configure` or makejinja
3. **Bootstrap tasks** focus on ansible and flux, not templating
4. **Renovate** updates versions directly in your YAML files

## Getting Started

1. Start with quick wins (07, 08, 06) to build momentum
2. Implement mise (01) to simplify your dev environment
3. Clean up taskfiles (09) to remove template-related tasks
4. Add new components (05a, 05c) as needed
5. Consider larger changes (02, 04) based on your needs

