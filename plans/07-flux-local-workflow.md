# Plan: Improved Flux Local Workflow

## Overview

Enhance the GitHub Actions workflow for flux-local to include validation tests, better diff formatting, and status checks.

## Current State

Your `.github/workflows/flux-diff.yaml`:
- Runs on PR to main
- Diffs helmrelease and kustomization
- Posts diff as PR comment

## Target State

Enhanced workflow with:
- Pre-job to check if kubernetes files changed
- flux-local test step for validation
- Better diff formatting
- Status check job for CI gates
- Step summary output

## Implementation Steps

### Step 1: Update flux-local workflow

Replace `.github/workflows/flux-diff.yaml` with:

```yaml
---
name: "Flux Local"

on:
  pull_request:
    branches: ["main"]

concurrency:
  group: ${{ github.workflow }}-${{ github.event.number || github.ref }}
  cancel-in-progress: true

jobs:
  pre-job:
    name: Flux Local Pre-Job
    runs-on: ubuntu-latest
    outputs:
      any_changed: ${{ steps.changed-files.outputs.any_changed }}
    steps:
      - name: Checkout
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: Get Changed Files
        id: changed-files
        uses: tj-actions/changed-files@ed68ef82c095e0d48ec87eccea555d944a631a4c # v46.0.5
        with:
          files: kubernetes/**

  test:
    name: Flux Local Test
    needs: pre-job
    runs-on: ubuntu-latest
    if: ${{ needs.pre-job.outputs.any_changed == 'true' }}
    steps:
      - name: Checkout
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: Run flux-local test
        uses: docker://ghcr.io/allenporter/flux-local:v8.0.1
        with:
          args: >-
            test
            --enable-helm
            --all-namespaces
            --path /github/workspace/kubernetes/main/flux
            -v

  diff:
    name: Flux Local Diff
    needs: pre-job
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    strategy:
      matrix:
        resources: ["helmrelease", "kustomization"]
      max-parallel: 4
      fail-fast: false
    if: ${{ needs.pre-job.outputs.any_changed == 'true' }}
    steps:
      - name: Checkout Pull Request Branch
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          path: pull

      - name: Checkout Default Branch
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          ref: "${{ github.event.repository.default_branch }}"
          path: default

      - name: Run flux-local diff
        uses: docker://ghcr.io/allenporter/flux-local:v8.0.1
        with:
          args: >-
            diff ${{ matrix.resources }}
            --unified 6
            --path /github/workspace/pull/kubernetes/main/flux
            --path-orig /github/workspace/default/kubernetes/main/flux
            --strip-attrs "helm.sh/chart,checksum/config,app.kubernetes.io/version,chart"
            --limit-bytes 10000
            --all-namespaces
            --sources "home-kubernetes"
            --output-file diff.patch

      - name: Generate Diff
        id: diff
        run: |
          cat diff.patch;
          {
              echo 'diff<<EOF'
              cat diff.patch
              echo EOF
          } >> "$GITHUB_OUTPUT";
          {
              echo "### ${{ matrix.resources }} Diff"
              echo '```diff'
              cat diff.patch
              echo '```'
          } >> "$GITHUB_STEP_SUMMARY"

      - name: Add Comment
        if: ${{ steps.diff.outputs.diff != '' }}
        continue-on-error: true
        uses: mshick/add-pr-comment@b8f338c590a895d50bcbfa6c5859251edc8952fc # v2.8.2
        with:
          message-id: "${{ github.event.pull_request.number }}/kubernetes/${{ matrix.resources }}"
          message-failure: Diff was not successful
          message: |
            ### ${{ matrix.resources }} changes
            ```diff
            ${{ steps.diff.outputs.diff }}
            ```

  flux-local-status:
    name: Flux Local Success
    needs: ["test", "diff"]
    runs-on: ubuntu-latest
    if: ${{ always() }}
    steps:
      - name: Any jobs failed?
        if: ${{ contains(needs.*.result, 'failure') }}
        run: exit 1

      - name: All jobs passed or skipped?
        if: ${{ !(contains(needs.*.result, 'failure')) }}
        run: echo "All jobs passed or skipped" && echo "${{ toJSON(needs.*.result) }}"
```

### Step 2: Update paths in workflow

Adjust paths to match your repository structure:
- `kubernetes/main/flux` - your flux kustomization path
- `home-kubernetes` - your GitRepository name

### Step 3: Add branch protection rule (optional)

In GitHub repository settings, add branch protection for `main`:
- Require status checks: `Flux Local Success`

## k3s Compatibility

✅ **Fully compatible** - This is purely a CI/CD workflow with no cluster runtime dependencies.

## New Features Explained

### Pre-job
Checks if any kubernetes files changed before running expensive diff jobs. Skips the workflow entirely if no relevant changes.

### Test Job
Runs `flux-local test` which validates:
- Kustomization builds correctly
- HelmReleases render without errors
- No invalid YAML

### Status Check Job
Provides a single status check (`Flux Local Success`) that:
- Passes if all jobs pass or skip
- Fails if any job fails
- Can be used as a required check for branch protection

### Step Summary
Writes diff output to GitHub Actions step summary for easy viewing without comments.

## Benefits

- Faster CI when no kubernetes changes
- Validation catches errors before merge
- Single status check for branch protection
- Better visibility with step summaries
- Parallel diff jobs for speed

## Dependencies

None - can be implemented independently.

## Estimated Effort

~30 minutes

## Testing

1. Create a PR with kubernetes changes
2. Verify pre-job detects changes
3. Verify test job validates manifests
4. Verify diff jobs post comments
5. Verify status check reports correctly
6. Create a PR with non-kubernetes changes, verify workflow skips

