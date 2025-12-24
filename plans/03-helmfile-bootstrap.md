# Plan: Helmfile Bootstrap Process

> **Status: OPTIONAL** - Since you already have a running cluster with generated configs, this plan is mainly useful for:
> - Rebuilding the cluster from scratch
> - Setting up additional clusters
> - Documenting the bootstrap process

## Overview

Implement a helmfile-based bootstrap process for deploying core cluster components in the correct order with proper dependency management.

## Current State

- Bootstrap relies on ansible playbooks for k3s
- Manual helm/kubectl commands for some components
- No structured bootstrap for core Kubernetes components after cluster creation

## Target State

- Helmfile manages initial deployment of core components
- Proper dependency ordering (cilium → coredns → cert-manager → flux)
- Idempotent bootstrap process
- Nice logging and error handling

## Implementation Steps

### Step 1: Create bootstrap directory structure

```
bootstrap/
├── helmfile.d/
│   ├── 00-crds.yaml
│   └── 01-apps.yaml
├── templates/
│   └── values.yaml.gotmpl
└── scripts/
    ├── bootstrap-apps.sh
    └── lib/
        └── common.sh
```

### Step 2: Create helmfile for CRDs

**bootstrap/helmfile.d/00-crds.yaml:**
```yaml
---
helmDefaults:
  cleanupOnFail: true
  wait: true
  waitForJobs: true

releases:
  - name: prometheus-operator-crds
    namespace: monitoring
    chart: oci://ghcr.io/prometheus-community/charts/prometheus-operator-crds
    version: 19.1.0
```

### Step 3: Create helmfile for apps

**bootstrap/helmfile.d/01-apps.yaml:**
```yaml
---
helmDefaults:
  cleanupOnFail: true
  wait: true
  waitForJobs: true

releases:
  - name: cilium
    namespace: kube-system
    chart: oci://ghcr.io/home-operations/charts-mirror/cilium
    version: 1.18.5
    values: ['./templates/values.yaml.gotmpl']

  - name: coredns
    namespace: kube-system
    chart: oci://ghcr.io/coredns/charts/coredns
    version: 1.45.0
    values: ['./templates/values.yaml.gotmpl']
    needs: ['kube-system/cilium']

  - name: cert-manager
    namespace: cert-manager
    chart: oci://quay.io/jetstack/charts/cert-manager
    version: v1.19.2
    values: ['./templates/values.yaml.gotmpl']
    needs: ['kube-system/coredns']

  - name: flux-operator
    namespace: flux-system
    chart: oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator
    version: 0.37.1
    values: ['./templates/values.yaml.gotmpl']
    needs: ['cert-manager/cert-manager']

  - name: flux-instance
    namespace: flux-system
    chart: oci://ghcr.io/controlplaneio-fluxcd/charts/flux-instance
    version: 0.37.1
    values: ['./templates/values.yaml.gotmpl']
    needs: ['flux-system/flux-operator']
```

### Step 4: Create values template

**bootstrap/templates/values.yaml.gotmpl:**
```yaml
{{- $release := .Release.Name -}}
{{- if eq $release "cilium" }}
# Cilium values for k3s
kubeProxyReplacement: true
k8sServiceHost: {{ requiredEnv "K3S_API_HOST" }}
k8sServicePort: 6443
# ... additional cilium config
{{- end }}

{{- if eq $release "cert-manager" }}
crds:
  enabled: true
{{- end }}

# ... other release values
```

### Step 5: Create logging library

**scripts/lib/common.sh:**
```bash
#!/usr/bin/env bash
set -Eeuo pipefail

function log() {
    local level="${1:-info}"
    shift
    local -A level_priority=([debug]=1 [info]=2 [warn]=3 [error]=4)
    local current_priority=${level_priority[$level]:-2}
    local configured_level=${LOG_LEVEL:-info}
    local configured_priority=${level_priority[$configured_level]:-2}

    if ((current_priority < configured_priority)); then
        return
    fi

    local -A colors=(
        [debug]="\033[1m\033[38;5;63m"
        [info]="\033[1m\033[38;5;87m"
        [warn]="\033[1m\033[38;5;192m"
        [error]="\033[1m\033[38;5;198m"
    )

    local color="${colors[$level]:-${colors[info]}}"
    local msg="$1"
    shift

    local data=
    if [[ $# -gt 0 ]]; then
        for item in "$@"; do
            if [[ "${item}" == *=* ]]; then
                data+="\033[1m\033[38;5;236m${item%%=*}=\033[0m\"${item#*=}\" "
            else
                data+="${item} "
            fi
        done
    fi

    local output_stream="/dev/stdout"
    if [[ "$level" == "error" ]]; then
        output_stream="/dev/stderr"
    fi

    printf "%s %b%s%b %s %b\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        "${color}" "${level^^}" "\033[0m" "${msg}" "${data}" >"${output_stream}"

    if [[ "$level" == "error" ]]; then
        exit 1
    fi
}

function check_env() {
    local envs=("${@}")
    local missing=()
    for env in "${envs[@]}"; do
        if [[ -z "${!env-}" ]]; then
            missing+=("${env}")
        fi
    done
    if [ ${#missing[@]} -ne 0 ]; then
        log error "Missing required env variables" "envs=${missing[*]}"
    fi
}

function check_cli() {
    local deps=("${@}")
    local missing=()
    for dep in "${deps[@]}"; do
        if ! command -v "${dep}" &>/dev/null; then
            missing+=("${dep}")
        fi
    done
    if [ ${#missing[@]} -ne 0 ]; then
        log error "Missing required deps" "deps=${missing[*]}"
    fi
}
```

### Step 6: Create bootstrap script

**scripts/bootstrap-apps.sh:**
```bash
#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"

export LOG_LEVEL="${LOG_LEVEL:-info}"
export ROOT_DIR="$(git rev-parse --show-toplevel)"

function apply_namespaces() {
    log debug "Applying namespaces"
    local namespaces=("kube-system" "cert-manager" "flux-system" "network" "monitoring")
    for ns in "${namespaces[@]}"; do
        if kubectl get namespace "${ns}" &>/dev/null; then
            log info "Namespace exists" "namespace=${ns}"
        else
            kubectl create namespace "${ns}"
            log info "Namespace created" "namespace=${ns}"
        fi
    done
}

function apply_sops_secrets() {
    log debug "Applying SOPS secrets"
    # Apply age key secret for flux
    if [[ -f "${ROOT_DIR}/age.key" ]]; then
        kubectl -n flux-system create secret generic sops-age \
            --from-file=age.agekey="${ROOT_DIR}/age.key" \
            --dry-run=client -o yaml | kubectl apply -f -
        log info "SOPS age secret applied"
    fi
}

function sync_helm_releases() {
    log debug "Syncing Helm releases"
    local helmfile_file="${ROOT_DIR}/bootstrap/helmfile.d/01-apps.yaml"

    if [[ ! -f "${helmfile_file}" ]]; then
        log error "Helmfile not found" "file=${helmfile_file}"
    fi

    if ! helmfile --file "${helmfile_file}" sync --hide-notes; then
        log error "Failed to sync Helm releases"
    fi

    log info "Helm releases synced successfully"
}

function main() {
    check_env KUBECONFIG
    check_cli helmfile kubectl sops

    apply_namespaces
    apply_sops_secrets
    sync_helm_releases

    log info "Bootstrap complete! Flux is now syncing the Git repository"
}

main "$@"
```

### Step 7: Add task to Taskfile

```yaml
bootstrap:apps:
  desc: Bootstrap apps into the cluster
  cmd: bash {{.SCRIPTS_DIR}}/bootstrap-apps.sh
  preconditions:
    - test -f {{.KUBECONFIG}}
    - test -f {{.ROOT_DIR}}/bootstrap/helmfile.d/01-apps.yaml
```

## k3s Compatibility

✅ **Fully compatible** - Helmfile works with any Kubernetes distribution. The values templates can be customized for k3s-specific configurations.

**k3s-specific considerations:**
- k3s API server endpoint configuration
- k3s already includes CoreDNS (may want to skip or replace)
- Cilium configuration differs slightly for k3s vs Talos

## Benefits

- Declarative bootstrap process
- Proper dependency management
- Idempotent operations
- Better error handling and logging
- Easier to reproduce and debug

## Dependencies

- Plan 01 (mise configuration) - for helmfile CLI tool
- May want to coordinate with Plan 02 (flux-operator)

## Estimated Effort

~3-4 hours

## Testing

1. Test helmfile template rendering: `helmfile template`
2. Test on a fresh k3s cluster
3. Verify all components start in correct order
4. Test idempotency by running bootstrap twice

