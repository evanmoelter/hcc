# Plan: Improved Renovate Configuration

## Overview

Update the Renovate configuration to include new managers, better auto-merge rules, and improved grouping for related packages.

## Current State

Your current `.github/renovate.json5` includes:
- Basic flux, helm-values, kubernetes managers
- Custom regex for dependencies
- Semantic commit formatting
- k3s versioning regex

## Target State

Enhanced Renovate config with:
- Helmfile manager support
- mise tool auto-merge
- OCI dependency regex
- Flux-operator grouping
- Better auto-merge rules
- GitHub Actions digest pinning

## Implementation Steps

### Step 1: Update renovate.json5

Replace/update `.github/renovate.json5` with:

```json5
{
  $schema: "https://docs.renovatebot.com/renovate-schema.json",
  extends: [
    "config:recommended",
    "docker:enableMajor",
    "helpers:pinGitHubActionDigests",  // Pin GH Actions to digests
    ":automergeBranch",
    ":dependencyDashboard",
    ":disableRateLimiting",
    ":semanticCommits",
  ],
  dependencyDashboard: true,
  dependencyDashboardTitle: "Renovate Dashboard 🤖",
  schedule: ["every weekend"],
  ignorePaths: ["**/*.sops.*"],
  
  // Manager configurations
  flux: {
    managerFilePatterns: [
      "/(^|/)ansible/.+\\.ya?ml(\\.j2)?$/",
      "/(^|/)kubernetes/.+\\.ya?ml(\\.j2)?$/",
    ],
  },
  helmfile: {
    managerFilePatterns: [
      "/(^|/)helmfile\\.ya?ml(\\.gotmpl)?(\\.j2)?$/",
      "/(^|/)helmfile\\.d/.+\\.ya?ml(\\.gotmpl)?(\\.j2)?$/",
    ],
  },
  kubernetes: {
    managerFilePatterns: [
      "/(^|/)ansible/.+\\.ya?ml(\\.j2)?$/",
      "/(^|/)kubernetes/.+\\.ya?ml(\\.j2)?$/",
    ],
  },
  kustomize: {
    managerFilePatterns: ["/^kustomization\\.ya?ml(\\.j2)?$/"],
  },
  "pip_requirements": {
    managerFilePatterns: [
      "/(^|/)[\\w-]*requirements(-\\w+)?\\.(txt|pip)(\\.j2)?$/",
    ],
  },
  "ansible-galaxy": {
    managerFilePatterns: [
      "/(^|/)(galaxy|requirements)(\\.ansible)?\\.ya?ml(\\.j2)?$/",
    ],
  },
  
  packageRules: [
    // Auto-merge GitHub Actions (minor/patch)
    {
      description: "Auto-merge GitHub Actions",
      matchManagers: ["github-actions"],
      automerge: true,
      automergeType: "branch",
      matchUpdateTypes: ["minor", "patch", "digest"],
      minimumReleaseAge: "3 days",
      ignoreTests: true,
    },
    
    // Auto-merge mise tools
    {
      description: "Auto-merge Mise Tools",
      matchManagers: ["mise"],
      automerge: true,
      automergeType: "branch",
      matchUpdateTypes: ["minor", "patch"],
      ignoreTests: true,
    },
    
    // Flux Operator Group
    {
      description: "Flux Operator Group",
      groupName: "flux-operator",
      matchDatasources: ["docker"],
      matchPackageNames: ["/flux-operator/", "/flux-instance/", "/flux-operator-manifests/"],
      group: {
        commitMessageTopic: "{{{groupName}}} group",
      },
      minimumGroupSize: 3,
    },
    
    // Flux Group
    {
      description: "Flux Group",
      groupName: "Flux",
      matchDatasources: ["docker", "github-tags"],
      versioning: "semver",
      group: {
        commitMessageTopic: "{{{groupName}}} group",
      },
      separateMinorPatch: true,
      matchPackageNames: ["/flux/"],
    },
    
    // System Upgrade Controller Group
    {
      description: "System Upgrade Controller Group",
      groupName: "System Upgrade Controller",
      matchDatasources: ["docker", "github-releases"],
      group: {
        commitMessageTopic: "{{{groupName}}} group",
      },
      matchPackageNames: ["/system-upgrade-controller/"],
    },
    
    // k3s versioning
    {
      description: "Use custom versioning for k3s",
      matchDatasources: ["github-releases"],
      versioning: "regex:^v(?<major>\\d+)\\.(?<minor>\\d+)\\.(?<patch>\\d+)(?<compatibility>\\+k.s)\\.?(?<build>\\d+)$",
      matchPackageNames: ["/k3s/"],
    },
    
    // Semantic commits by update type
    {
      matchUpdateTypes: ["major"],
      semanticCommitType: "feat",
      commitMessagePrefix: "{{semanticCommitType}}({{semanticCommitScope}})!:",
      commitMessageExtra: "( {{currentVersion}} → {{newVersion}} )",
    },
    {
      matchUpdateTypes: ["minor"],
      semanticCommitType: "feat",
      commitMessageExtra: "( {{currentVersion}} → {{newVersion}} )",
    },
    {
      matchUpdateTypes: ["patch"],
      semanticCommitType: "fix",
      commitMessageExtra: "( {{currentVersion}} → {{newVersion}} )",
    },
    {
      matchUpdateTypes: ["digest"],
      semanticCommitType: "chore",
      commitMessageExtra: "( {{currentDigestShort}} → {{newDigestShort}} )",
    },
    
    // Semantic scopes by datasource
    {
      matchDatasources: ["docker"],
      semanticCommitScope: "container",
      commitMessageTopic: "image {{depName}}",
    },
    {
      matchDatasources: ["helm"],
      semanticCommitScope: "helm",
      commitMessageTopic: "chart {{depName}}",
    },
    {
      matchManagers: ["github-actions"],
      semanticCommitType: "ci",
      semanticCommitScope: "github-action",
      commitMessageTopic: "action {{depName}}",
    },
    {
      matchDatasources: ["github-releases"],
      semanticCommitScope: "github-release",
      commitMessageTopic: "release {{depName}}",
    },
    {
      matchManagers: ["mise"],
      semanticCommitScope: "mise",
      commitMessageTopic: "tool {{depName}}",
    },
    {
      matchDatasources: ["galaxy", "galaxy-collection"],
      semanticCommitScope: "ansible",
      commitMessageTopic: "collection {{depName}}",
    },
    
    // Labels by update type
    {
      matchUpdateTypes: ["major"],
      labels: ["type/major"],
    },
    {
      matchUpdateTypes: ["minor"],
      labels: ["type/minor"],
    },
    {
      matchUpdateTypes: ["patch"],
      labels: ["type/patch"],
    },
    {
      matchUpdateTypes: ["digest"],
      labels: ["type/digest"],
    },
    
    // Labels by datasource
    {
      matchDatasources: ["docker"],
      addLabels: ["renovate/container"],
    },
    {
      matchDatasources: ["helm"],
      addLabels: ["renovate/helm"],
    },
    {
      matchManagers: ["github-actions"],
      addLabels: ["renovate/github-action"],
    },
    {
      matchDatasources: ["github-releases"],
      addLabels: ["renovate/github-release"],
    },
    {
      matchDatasources: ["galaxy", "galaxy-collection"],
      addLabels: ["renovate/ansible"],
    },
  ],
  
  customManagers: [
    // Annotated dependencies
    {
      description: "Process annotated dependencies",
      customType: "regex",
      managerFilePatterns: [
        "/(^|/).+\\.env(\\.j2)?$/",
        "/(^|/).+\\.sh(\\.j2)?$/",
        "/(^|/).+\\.ya?ml(\\.j2)?$/",
        "/(^|/).taskfiles/.+\\.ya?ml$/",
      ],
      matchStrings: [
        "datasource=(?<datasource>\\S+) depName=(?<depName>\\S+)( repository=(?<registryUrl>\\S+))?\\n.+(:\\s|=)(&\\S+\\s)?(?<currentValue>\\S+)",
        "datasource=(?<datasource>\\S+) depName=(?<depName>\\S+)\\n.+/(?<currentValue>(v|\\d)[^/]+)",
      ],
      datasourceTemplate: "{{#if datasource}}{{{datasource}}}{{else}}github-releases{{/if}}",
    },
    // OCI dependencies
    {
      customType: "regex",
      description: "Process OCI dependencies",
      managerFilePatterns: ["/\\.yaml(\\.j2)?$/"],
      matchStrings: ["oci://(?<depName>[^:]+):(?<currentValue>\\S+)"],
      datasourceTemplate: "docker",
    },
  ],
}
```

### Step 2: Move renovate.json5 to root (optional)

The template places `.renovaterc.json5` in the root directory. You can either:
- Keep it in `.github/renovate.json5` (current location)
- Move to `.renovaterc.json5` in root

Both locations work.

## k3s Compatibility

✅ **Fully compatible** - Renovate configuration is cluster-agnostic.

The k3s-specific versioning regex is already included to handle k3s version strings like `v1.29.0+k3s1`.

## Benefits

- Helmfile support for bootstrap process
- mise tools auto-merged
- OCI references in YAML files detected
- Related packages grouped together
- Better commit messages with version ranges
- GH Actions pinned to digests for security

## New Features Explained

| Feature | Description |
|---------|-------------|
| `helpers:pinGitHubActionDigests` | Pins GH Actions to SHA digests |
| `helmfile` manager | Detects chart versions in helmfiles |
| `mise` manager | Detects tools in mise.toml |
| OCI regex matcher | Finds `oci://image:tag` patterns |
| `minimumReleaseAge` | Waits 3 days before auto-merge |

## Dependencies

- Plan 01 (mise) - for mise manager to have files to scan
- Plan 03 (helmfile) - for helmfile manager to have files to scan

## Estimated Effort

~30 minutes

## Testing

1. Push the updated config
2. Check Renovate Dashboard issue for detected dependencies
3. Verify helmfile charts are detected
4. Verify mise tools are detected
5. Test auto-merge by making a minor GH Action update available

