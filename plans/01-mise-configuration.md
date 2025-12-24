# Plan: Complete mise Configuration

## Overview

Upgrade the current minimal `mise.toml` to a comprehensive configuration that manages all CLI tools and environment variables automatically.

> **Note:** Since you're working with generated configs directly (not maintaining templates), makejinja and Python venv are not needed.

## Current State

```toml
[tools]
node = "24"
```

## Target State

A complete mise configuration that:
- Manages all required CLI tools via aqua backend
- Sets environment variables (KUBECONFIG, SOPS_AGE_KEY_FILE)
- Eliminates need for Brewfile

## Implementation Steps

### Step 1: Create comprehensive `.mise.toml`

Replace the current `mise.toml` with:

```toml
[env]
KUBECONFIG = "{{config_root}}/kubeconfig"
SOPS_AGE_KEY_FILE = "{{config_root}}/age.key"

[tools]
"node" = "24"
"aqua:cilium/cilium-cli" = "0.18.9"
"aqua:cli/cli" = "2.83.2"
"aqua:cloudflare/cloudflared" = "2025.11.1"
"aqua:FiloSottile/age" = "1.2.1"
"aqua:fluxcd/flux2" = "2.7.5"
"aqua:getsops/sops" = "3.11.0"
"aqua:go-task/task" = "3.46.3"
"aqua:helm/helm" = "3.19.4"
"aqua:helmfile/helmfile" = "1.2.3"
"aqua:jqlang/jq" = "1.8.1"
"aqua:kubernetes-sigs/kustomize" = "5.7.1"
"aqua:kubernetes/kubernetes/kubectl" = "1.35.0"
"aqua:mikefarah/yq" = "4.50.1"
"aqua:yannh/kubeconform" = "0.7.0"
"aqua:derailed/k9s" = "latest"
"aqua:stern/stern" = "latest"
```

### Step 2: Update Taskfile to remove redundant tasks

The following tasks in `.taskfiles/Workstation/Taskfile.yaml` can be removed entirely:
- `venv` - not needed without templates
- `brew` - tools now managed by mise
- `generic-linux` - tools now managed by mise

Keep `direnv` task for now as it's still useful.

### Step 3: Update `.envrc` for direnv integration

Skip this step, will be handled manually.

### Step 4: Remove or archive Brewfile

The `Brewfile` and `Archfile` in `.taskfiles/Workstation/` can be archived or removed.

### Step 5: Remove requirements.txt

Since you're not using makejinja/templates, the `requirements.txt` file can be removed entirely.

### Step 6: Trust mise configuration

```bash
mise trust
mise install
```

## k3s Compatibility

✅ **Fully compatible** - This is purely a developer tooling change with no impact on cluster runtime.

## Benefits

- Single source of truth for all CLI tools
- Version pinning for reproducibility
- Cross-platform support (macOS, Linux)
- Automatic environment setup
- Renovate can auto-update tool versions

## Dependencies

None - this can be implemented independently.

## Estimated Effort

~1-2 hours

## Testing

1. Run `mise install` and verify all tools are available
2. Verify `$KUBECONFIG` and `$SOPS_AGE_KEY_FILE` are set correctly
3. Run existing tasks to ensure nothing breaks
4. Test on a fresh clone to verify setup experience

