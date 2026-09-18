---
name: add-apollo-app
description: Add a new application to the Apollo Kubernetes cluster, from app research and operator decisions through Flux manifests and validation.
---

# Add an Apollo app

Implement a new app under `kubernetes/apollo/apps/<namespace>/<app>/`. Run repository commands from
the checkout root and resolve this skill's links relative to their containing file.

## Research and decisions

Check whether the app already exists, then inspect one or two current Apollo apps with similar needs.
Invoke [community-discovery](../community-discovery/SKILL.md) if its findings for this task are not
already available. Reuse that research and verify the app's requirements against upstream documentation
and the selected chart. Prefer a usable app-specific chart, otherwise bjw-s app-template. Check current
releases and compatibility rather than inheriting an example's pins.

Report the proposed deployment and sources before implementation. Ask only about decisions that
research and existing user instructions cannot settle: intended LAN/public/Tailscale access and
authentication, data durability and backup needs, unusual capacity or hardware requirements, or
material chart/image tradeoffs. A community app's public route is not permission to expose this app.
Propose the app name, an existing namespace, and ordinary technical settings rather than making the
operator choose documented ports or repeat settled conventions. If a new namespace is needed, explain why.

For missing credentials, propose item names and exact field labels using the documented secret setup;
get confirmation of existing names rather than inventing them. Wait for explicit answers to blocking
decisions; continue independent research while waiting.

## Integrations and implementation

Use the [documentation index](../../../docs/index.md) to read the integration instructions needed by
this app. Determine what data needs persistence, whether it starts empty or restores existing data,
and what dependencies must be ready before the app starts. Follow the owning docs for resource
lifecycles, credentials, backups, and any initialization cleanup.

Check available capacity and replica placement when sizing durable volumes. If live checks are
unavailable, record capacity as unverified. Missing platform readiness or credentials can leave
deployment blocked without preventing manifest work; report those prerequisites.

Scaffold the app using the [repository layout](../../../AGENTS.md#how-an-app-is-laid-out) and
[manifest conventions](../../../AGENTS.md#patterns). Apply the selected integrations through their
own lifecycles and readiness gates. Choose app-specific probes, writable temporary mounts, and an
update strategy compatible with the app's state and volume access mode.

Register every Flux satellite and resource in its owning Kustomization. For a new namespace, verify
its inclusion in the Flux root build. Check reachability from `kubernetes/apollo/flux`, not just file existence.

## Validate and hand off

Run the applicable [repository validation](../../../AGENTS.md#validating-changes), including schema
checks, policy lint, and Flux/Helm rendering. Inspect affected rendered resources for expected
workloads, routes, secret references, storage, databases, and backups. Check substitutions and
chart-generated Service names and ports; report unavailable inputs and validation limitations.

Update the owning documentation for new architecture or reusable operational facts. Follow the
available Graphite workflow when committing or opening PRs is in scope.

Finish with what was added, validation results, operator credential/prerequisite work, and concrete
post-deployment checks: Flux/Helm readiness, real application behavior, each intended access path,
authentication/proxy trust where relevant, and the first successful offsite backup for durable data.
Include any required post-deployment cleanup. Distinguish rendered configuration from observed live behavior.
