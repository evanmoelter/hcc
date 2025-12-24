# Implementation Plans

This directory contains implementation plans for improvements identified from the upstream [onedr0p/cluster-template](https://github.com/onedr0p/cluster-template).

## Plan Overview

| # | Plan | Effort | Dependencies | Priority |
|---|------|--------|--------------|----------|
| 01 | [mise Configuration](./01-mise-configuration.md) | 1-2h | None | High |
| 02 | [Flux Operator](./02-flux-operator.md) | 4-6h | None | Medium |
| 03 | [Helmfile Bootstrap](./03-helmfile-bootstrap.md) | 3-4h | 01 | Medium |
| 04 | [Envoy Gateway](./04-envoy-gateway.md) | 6-8h | None | Low |
| 05a | [Spegel](./05a-spegel.md) | 1h | None | Medium |
| 05b | [CoreDNS Helm](./05b-coredns-helm.md) | 2-3h | None | Low |
| 05c | [Cloudflare DNS](./05c-cloudflare-dns.md) | 1-2h | None | Medium |
| 06 | [Renovate Improvements](./06-renovate-improvements.md) | 30m | 01, 03 | High |
| 07 | [Flux Local Workflow](./07-flux-local-workflow.md) | 30m | None | High |
| 08 | [HelmRelease Defaults](./08-helmrelease-defaults.md) | 30m | None | High |
| 09 | [Simplified Taskfiles](./09-simplified-taskfiles.md) | 2h | 01 | Medium |
| 10 | [makejinja Improvements](./10-makejinja-improvements.md) | 30m | None | Low |

## Recommended Implementation Order

### Quick Wins (< 1 hour each)
1. **07 - Flux Local Workflow** - Better CI/CD
2. **08 - HelmRelease Defaults** - Improved reliability
3. **06 - Renovate Improvements** - Better dependency management
4. **10 - makejinja Improvements** - Template enhancements

### Foundation (implement together)
5. **01 - mise Configuration** - Developer tooling foundation
6. **09 - Simplified Taskfiles** - Streamlined workflows

### New Components (independent)
7. **05a - Spegel** - P2P image distribution
8. **05c - Cloudflare DNS** - Automatic DNS management

### Larger Changes (plan carefully)
9. **02 - Flux Operator** - Major Flux change
10. **03 - Helmfile Bootstrap** - New bootstrap process

### Optional / Consider Later
11. **04 - Envoy Gateway** - Major ingress migration
12. **05b - CoreDNS Helm** - Only if needed

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
- **makejinja**: ✅ Fully compatible

## Getting Started

1. Read through the plans in order of priority
2. Start with quick wins to build momentum
3. Implement foundation changes together
4. Add new components as needed
5. Consider larger changes based on your needs

