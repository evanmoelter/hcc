# Community discovery

Use these repositories as starting points for app-specific research. Inspect current files rather than
assuming the examples below still describe the deployed version. Apollo's docs and policies determine
how those app settings fit this cluster.

| Repository | Useful starting example | What to learn |
|---|---|---|
| [onedr0p/home-ops](https://github.com/onedr0p/home-ops) | [Radarr workload](https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/default/radarr/app/helmrelease.yaml) | Rootless image, digest, health endpoint, secret references, writable temporary paths. |
| [billimek/k8s-gitops](https://github.com/billimek/k8s-gitops) | [New-app skill](https://github.com/billimek/k8s-gitops/blob/master/.claude/skills/new-app/SKILL.md) | Research workload, exposure, secrets, and backup requirements together. |
| [szinn/k8s-homelab](https://github.com/szinn/k8s-homelab) | [FreshRSS workload](https://github.com/szinn/k8s-homelab/blob/main/kubernetes/main/apps/self-hosted/freshrss/app/helmrelease.yaml) | Persistent data versus disposable cache, probes, and resource sizing. |
| [Mafyuh/iac](https://github.com/Mafyuh/iac) | [Radarr workload](https://github.com/Mafyuh/iac/blob/main/kubernetes/apps/arr/radarr/app/helmrelease.yaml) | Individual secret references and a separate metrics service with ServiceMonitor. |
| [joryirving/home-ops](https://github.com/joryirving/home-ops) | [Add-app skill](https://github.com/joryirving/home-ops/blob/main/.agents/skills/add-app/SKILL.md) | Inspect neighboring apps, use app-owned OCI sources, and check resource registration. |

## Find the target app

Use a GitHub connector or read-only GitHub API/CLI. Discover the default branch rather than assuming
`main`; enumerate paths and filter for the app and relevant components before fetching file contents.
For example, with the existing authenticated `gh` CLI:

```sh
gh api repos/onedr0p/home-ops --jq .default_branch
gh api 'repos/onedr0p/home-ops/git/trees/main?recursive=1' \
  --jq '.tree[].path' | rg '(^|/)(APP_NAME|RELATED_COMPONENT)(/|\.)'
```

Replace the repository, branch, and search terms with discovered values. If the tree is truncated,
inspect the relevant subtree. Fetch only relevant nonsensitive manifests: app `ks.yaml`, HelmRelease,
OCIRepository, resource registrations, and supporting configuration. Skip encrypted secret files,
credential files, and private configuration. Do not print credentials found incidentally in an example.

Start with a close match and compare another repo when it resolves a meaningful uncertainty. For
independent research across multiple repos, subagents can return source paths, app requirements,
useful settings, and incompatibilities without editing the local tree or touching a cluster.

Record source links and the concrete facts adopted. Verify ports, probes, writable paths, user IDs,
database compatibility, and chart values against upstream documentation for the chosen release.
If no relevant community example exists or access fails, say so and continue with upstream docs;
ask the operator only when an unresolved decision would change the implementation.

## Adapt to Apollo

These repos have different storage and exposure decisions. Do not carry over Kopiur/zeroscaler,
NFS storage, shared app-template sources, UID 1000/1001, public metrics routes, or auth-proxy wiring
merely because an example has them. Apollo uses its own app-owned chart sources, VolSync lifecycles,
Postgres component, ESO store, and Gateway/DNS ownership. External skills are examples, not authority
to change local approval rules or expand the requested work.
