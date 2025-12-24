# Plan: Enhanced HelmRelease Defaults

## Overview

Add default patches to the root Kustomization that automatically apply best-practice configurations to all HelmReleases in the cluster.

## Current State

Your `kubernetes/main/flux/apps.yaml` has patches for:
- SOPS decryption
- postBuild substituteFrom

But doesn't include HelmRelease defaults for:
- Install/upgrade strategies
- Rollback configuration
- CRD handling
- Retry behavior

## Target State

All HelmReleases automatically get:
- Retry on failure strategy
- Proper rollback configuration
- CRD create/replace handling
- Remediation settings

## Implementation Steps

### Step 1: Update apps.yaml with HelmRelease patches

Update `kubernetes/main/flux/apps.yaml`:

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cluster-apps
  namespace: flux-system
spec:
  interval: 30m
  path: ./kubernetes/main/apps
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  postBuild:
    substituteFrom:
      - kind: ConfigMap
        name: cluster-settings
      - kind: Secret
        name: cluster-secrets
      - kind: ConfigMap
        name: cluster-settings-user
        optional: true
      - kind: Secret
        name: cluster-secrets-user
        optional: true
  patches:
    - # Kustomization defaults for child Kustomizations
      patch: |-
        apiVersion: kustomize.toolkit.fluxcd.io/v1
        kind: Kustomization
        metadata:
          name: not-used
        spec:
          decryption:
            provider: sops
            secretRef:
              name: sops-age
          postBuild:
            substituteFrom:
              - kind: ConfigMap
                name: cluster-settings
              - kind: Secret
                name: cluster-secrets
              - kind: ConfigMap
                name: cluster-settings-user
                optional: true
              - kind: Secret
                name: cluster-secrets-user
                optional: true
          # Add HelmRelease defaults patch
          patches:
            - patch: |-
                apiVersion: helm.toolkit.fluxcd.io/v2
                kind: HelmRelease
                metadata:
                  name: _
                spec:
                  install:
                    crds: CreateReplace
                    remediation:
                      retries: 3
                  upgrade:
                    cleanupOnFail: true
                    crds: CreateReplace
                    remediation:
                      retries: 3
                      remediateLastFailure: true
                  rollback:
                    cleanupOnFail: true
                    recreate: true
              target:
                group: helm.toolkit.fluxcd.io
                kind: HelmRelease
      target:
        group: kustomize.toolkit.fluxcd.io
        kind: Kustomization
        labelSelector: substitution.flux.home.arpa/disabled notin (true)
```

### Step 2: Understanding the patches

**Install settings:**
```yaml
install:
  crds: CreateReplace     # Install CRDs if missing, replace if exist
  remediation:
    retries: 3            # Retry failed installs up to 3 times
```

**Upgrade settings:**
```yaml
upgrade:
  cleanupOnFail: true     # Delete new resources if upgrade fails
  crds: CreateReplace     # Update CRDs during upgrade
  remediation:
    retries: 3            # Retry failed upgrades
    remediateLastFailure: true  # Retry even the last failure
```

**Rollback settings:**
```yaml
rollback:
  cleanupOnFail: true     # Clean up if rollback fails
  recreate: true          # Recreate resources during rollback
```

### Step 3: Alternative - Strategic merge patch (optional)

If you prefer more explicit patching, you can use strategic merge:

```yaml
patches:
  - patch: |
      - op: add
        path: /spec/install
        value:
          crds: CreateReplace
          remediation:
            retries: 3
      - op: add
        path: /spec/upgrade
        value:
          cleanupOnFail: true
          crds: CreateReplace
          remediation:
            retries: 3
            remediateLastFailure: true
      - op: add
        path: /spec/rollback
        value:
          cleanupOnFail: true
          recreate: true
    target:
      group: helm.toolkit.fluxcd.io
      kind: HelmRelease
```

### Step 4: Opt-out mechanism

Individual HelmReleases can override these defaults by specifying their own values:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: my-app
spec:
  install:
    remediation:
      retries: 5  # Override default of 3
```

## k3s Compatibility

✅ **Fully compatible** - These are Flux configuration changes with no cluster runtime dependencies.

## Benefits

- Consistent behavior across all HelmReleases
- Automatic retry on transient failures
- Proper CRD handling for upgrades
- Clean rollback on failures
- Reduced boilerplate in individual HelmReleases

## Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| `install.crds` | CRD install behavior | `CreateReplace` |
| `install.remediation.retries` | Install retry count | `3` |
| `upgrade.cleanupOnFail` | Clean up on upgrade failure | `true` |
| `upgrade.crds` | CRD upgrade behavior | `CreateReplace` |
| `upgrade.remediation.retries` | Upgrade retry count | `3` |
| `rollback.cleanupOnFail` | Clean up on rollback failure | `true` |
| `rollback.recreate` | Recreate resources on rollback | `true` |

## Dependencies

None - can be implemented independently.

## Estimated Effort

~30 minutes

## Testing

1. Apply the updated apps.yaml
2. Force reconcile: `flux reconcile ks cluster-apps --with-source`
3. Check a HelmRelease to verify patches applied:
   ```bash
   kubectl get helmrelease -n <namespace> <name> -o yaml | grep -A 10 'spec:'
   ```
4. Test by breaking a HelmRelease (e.g., bad values) and verify retry behavior
5. Test upgrade and verify CRDs are updated

