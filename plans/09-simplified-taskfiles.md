# Plan: Simplified Taskfile Structure

## Overview

Reorganize and simplify the Taskfile structure to reduce complexity while maintaining functionality needed for k3s clusters.

> **Note:** Since you're working with generated configs directly (not maintaining templates), all template-related tasks (`configure`, `.template`, etc.) can be removed entirely.

## Current State

Your `.taskfiles/` contains:
- `Ansible/` - k3s management via ansible
- `Flux/` - Flux operations
- `Kubernetes/` - kubectl operations
- `Repository/` - Git/repo operations
- `Sops/` - Secret encryption
- `Talos/` - Talos operations (may be unused with k3s)
- `Workstation/` - Tool installation

## Target State

Streamlined structure that:
- Removes redundancy with mise (Workstation tasks)
- Removes all template-related tasks
- Consolidates related tasks
- Keeps k3s/ansible support

## Implementation Steps

### Step 1: Simplify main Taskfile.yaml

Update root `Taskfile.yaml` (removing all template-related tasks):

```yaml
---
version: "3"

set: [pipefail]
shopt: [globstar]

vars:
  ANSIBLE_DIR: "{{.ROOT_DIR}}/ansible"
  KUBERNETES_DIR: "{{.ROOT_DIR}}/kubernetes/main"
  SCRIPTS_DIR: "{{.ROOT_DIR}}/scripts"

env:
  KUBECONFIG: "{{.ROOT_DIR}}/kubeconfig"
  SOPS_AGE_KEY_FILE: "{{.ROOT_DIR}}/age.key"

includes:
  ansible: .taskfiles/ansible
  flux: .taskfiles/flux
  kubernetes:
    aliases: ["k8s"]
    taskfile: .taskfiles/kubernetes
  sops: .taskfiles/sops
  user:
    taskfile: .taskfiles/user
    optional: true

tasks:
  default: task --list

  reconcile:
    desc: Force Flux to pull in changes from Git
    cmd: flux reconcile kustomization cluster-apps --with-source
    preconditions:
      - test -f {{.KUBECONFIG}}
      - which flux

  validate:
    desc: Validate Kubernetes manifests
    cmd: bash {{.SCRIPTS_DIR}}/kubeconform.sh {{.KUBERNETES_DIR}}
    preconditions:
      - which kubeconform
```

### Step 2: Simplify ansible taskfile

Update `.taskfiles/Ansible/Taskfile.yaml`:

```yaml
---
version: "3"

vars:
  ANSIBLE_PLAYBOOK_DIR: "{{.ANSIBLE_DIR}}/playbooks"
  ANSIBLE_INVENTORY_DIR: "{{.ANSIBLE_DIR}}/inventory"

tasks:
  deps:
    desc: Install Ansible dependencies
    cmd: ansible-galaxy install -r {{.ANSIBLE_DIR}}/requirements.yaml --force
    preconditions:
      - which ansible-galaxy

  install:
    desc: Install k3s cluster
    cmd: ansible-playbook -i {{.ANSIBLE_INVENTORY_DIR}}/hosts.yaml {{.ANSIBLE_PLAYBOOK_DIR}}/cluster-installation.yaml
    preconditions:
      - which ansible-playbook
      - test -f {{.ANSIBLE_INVENTORY_DIR}}/hosts.yaml

  prepare:
    desc: Prepare nodes for k3s
    cmd: ansible-playbook -i {{.ANSIBLE_INVENTORY_DIR}}/hosts.yaml {{.ANSIBLE_PLAYBOOK_DIR}}/cluster-prepare.yaml
    preconditions:
      - which ansible-playbook

  nuke:
    desc: Uninstall k3s cluster
    prompt: This will destroy the cluster... continue?
    cmd: ansible-playbook -i {{.ANSIBLE_INVENTORY_DIR}}/hosts.yaml {{.ANSIBLE_PLAYBOOK_DIR}}/cluster-nuke.yaml
    preconditions:
      - which ansible-playbook

  kubeconfig:
    desc: Fetch kubeconfig from cluster
    cmd: ansible-playbook -i {{.ANSIBLE_INVENTORY_DIR}}/hosts.yaml {{.ANSIBLE_PLAYBOOK_DIR}}/tasks/kubeconfig.yaml
    preconditions:
      - which ansible-playbook
```

### Step 3: Simplify flux taskfile

Update `.taskfiles/Flux/Taskfile.yaml`:

```yaml
---
version: "3"

tasks:
  reconcile:
    desc: Force reconcile all Flux resources
    cmds:
      - flux reconcile source git home-kubernetes
      - flux reconcile kustomization cluster-apps --with-source
    preconditions:
      - test -f {{.KUBECONFIG}}
      - which flux

  hr-restart:
    desc: Restart a HelmRelease [NS=namespace HR=name]
    cmd: flux suspend hr {{.HR}} -n {{.NS}} && flux resume hr {{.HR}} -n {{.NS}}
    requires:
      vars: [NS, HR]

  ks-restart:
    desc: Restart a Kustomization [KS=name]
    cmd: flux suspend ks {{.KS}} && flux resume ks {{.KS}}
    requires:
      vars: [KS]

  logs:
    desc: Show Flux controller logs
    cmd: kubectl logs -n flux-system -l app.kubernetes.io/part-of=flux --all-containers -f
    preconditions:
      - test -f {{.KUBECONFIG}}
```

### Step 4: Simplify kubernetes taskfile

Update `.taskfiles/Kubernetes/Taskfile.yaml`:

```yaml
---
version: "3"

tasks:
  resources:
    desc: Show cluster resources
    cmd: kubectl get nodes,pods -A -o wide

  kubeconform:
    desc: Validate Kubernetes manifests
    cmd: bash {{.SCRIPTS_DIR}}/kubeconform.sh {{.KUBERNETES_DIR}}
    preconditions:
      - which kubeconform

  debug:
    desc: Gather common resources for debugging
    cmds:
      - kubectl get nodes -o wide
      - kubectl get pods -A --field-selector=status.phase!=Running
      - kubectl get helmreleases -A
      - kubectl get kustomizations -A
      - kubectl get gitrepositories -A
    preconditions:
      - test -f {{.KUBECONFIG}}
```

### Step 5: Simplify sops taskfile

Update `.taskfiles/Sops/Taskfile.yaml`:

```yaml
---
version: "3"

tasks:
  age-keygen:
    desc: Generate age key for SOPS
    cmd: age-keygen -o {{.SOPS_AGE_KEY_FILE}}
    status:
      - test -f {{.SOPS_AGE_KEY_FILE}}
    preconditions:
      - which age-keygen

  encrypt:
    desc: Encrypt all SOPS files
    cmds:
      - |
        find {{.KUBERNETES_DIR}} -name "*.sops.*" -type f | while read -r file; do
          if [ "$(sops filestatus "$file" | jq -r '.encrypted')" = "false" ]; then
            sops --encrypt --in-place "$file"
          fi
        done
    preconditions:
      - test -f {{.SOPS_AGE_KEY_FILE}}
      - test -f {{.ROOT_DIR}}/.sops.yaml
      - which sops jq
```

### Step 6: Remove unneeded taskfiles and directories

Since mise handles tool installation and you're not using templates:

**Remove taskfile directories:**
- `.taskfiles/Workstation/` - mise handles tool installation
- `.taskfiles/Repository/` - if not used
- `.taskfiles/Talos/` - you're using k3s, not Talos

**Remove/archive template-related files:**
- `bootstrap/templates/` - template files
- `bootstrap/scripts/plugin.py` - makejinja plugin
- `bootstrap/scripts/validation.py` - template validation
- `makejinja.toml` - template config
- `config.sample.yaml` - template config sample
- `requirements.txt` - Python dependencies for templates

## k3s Compatibility

✅ **Fully compatible** - This plan specifically maintains k3s/ansible support while simplifying the overall structure.

## Directory Structure After

```
.taskfiles/
├── Ansible/
│   └── Taskfile.yaml
├── Flux/
│   └── Taskfile.yaml
├── Kubernetes/
│   └── Taskfile.yaml
├── Sops/
│   └── Taskfile.yaml
└── user/           # Optional user overrides
    └── Taskfile.yaml
```

## Benefits

- Cleaner task organization
- Less redundancy with mise
- Focused bootstrap workflow
- Easier to understand and maintain

## Dependencies

- Plan 01 (mise) should be implemented first to replace Workstation tasks

## Estimated Effort

~2 hours

## Testing

1. Run `task --list` to verify all tasks are available
2. Test each task group:
   - `task ansible:install` (if applicable)
   - `task sops:age-keygen`
   - `task flux:reconcile`
   - `task kubernetes:debug`
   - `task validate`

