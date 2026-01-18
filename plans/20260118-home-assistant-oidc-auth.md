# Plan: Home Assistant OIDC Authentication with Authentik

## Overview

Enable native OIDC authentication for Home Assistant using the [hass-oidc-auth](https://github.com/christiaangoossens/hass-oidc-auth) HACS component with Authentik as the identity provider. This approach is ingress-agnostic and will survive the planned nginx-ingress to Envoy Gateway migration without changes.

## Current State

- Home Assistant deployed with local authentication only
- OIDC credentials already provisioned in `home-assistant-secret`:
  - `HASS_OIDC_CLIENT_ID`
  - `HASS_OIDC_CLIENT_SECRET`
- Authentik running at `sso.${SECRET_DOMAIN}` with external ingress
- Configuration comment indicates OIDC is planned but not yet implemented

## Dependencies

| Dependency | Purpose | Status |
|------------|---------|--------|
| authentik | Identity provider | Deployed |
| home-assistant | Target application | Deployed |
| HACS | Integration installation | Declarative via env var |

## Architecture

```
User Browser
    │
    ├─► ha.${SECRET_DOMAIN} ──► Home Assistant
    │                              │
    │                              ▼
    │                         hass-oidc-auth
    │                              │
    │                              ▼
    └─► sso.${SECRET_DOMAIN} ──► Authentik
         (OIDC Provider)          │
                                  ▼
                             OAuth2 Flow
                                  │
                                  ▼
                         Callback to HA
```

## Implementation Steps

### Step 1: Create Authentik OAuth2/OIDC Provider

In Authentik admin (`https://sso.${SECRET_DOMAIN}/if/admin/`):

1. **Create Provider**:
   - Navigate to **Applications > Providers > Create**
   - Select **OAuth2/OpenID Provider**
   - Configure:
     - **Name**: `Home Assistant`
     - **Authorization flow**: `default-provider-authorization-explicit-consent`
     - **Client type**: `Confidential`
     - **Client ID**: Use value from `HASS_OIDC_CLIENT_ID` secret
     - **Client Secret**: Use value from `HASS_OIDC_CLIENT_SECRET` secret
     - **Redirect URIs**:
       ```
       https://ha.${SECRET_DOMAIN}/auth/oidc/callback
       https://ha.tail${SECRET_TAILNET_NAME}.ts.net/auth/oidc/callback
       ```
     - **Signing Key**: `authentik Self-signed Certificate`
     - **Scopes**: `openid`, `profile`, `email`, `groups` (if using RBAC)

2. **Create Application**:
   - Navigate to **Applications > Applications > Create**
   - Configure:
     - **Name**: `Home Assistant`
     - **Slug**: `home-assistant`
     - **Provider**: Select `Home Assistant` provider created above
     - **Launch URL**: `https://ha.${SECRET_DOMAIN}`

### Step 2: Enable HACS Declaratively

**Option A: Environment Variable (preferred if supported)**

The `ghcr.io/home-operations/home-assistant` image may support declarative HACS installation via env var:

```yaml
containers:
  app:
    env:
      # ... existing env vars ...
      HOME_ASSISTANT__HACS_INSTALL: "true"
```

**Option B: Init Container (fallback)**

If the env var doesn't work, use an init container to download and install HACS:

```yaml
initContainers:
  hacs-install:
    image:
      repository: busybox
      tag: 1.37.0
    command:
      - /bin/sh
      - -c
      - |
        HACS_VERSION="2.0.1"
        mkdir -p /config/custom_components
        rm -rf /config/custom_components/hacs
        busybox wget -qO- "https://github.com/hacs/integration/releases/download/${HACS_VERSION}/hacs.zip" | busybox unzip -d /config/custom_components/hacs -
    securityContext:
      runAsUser: 568
      runAsGroup: 568
```

Add the config volume mount to the init container in `persistence.config.advancedMounts`:

```yaml
persistence:
  config:
    advancedMounts:
      home-assistant:
        hacs-install:
          - path: /config
        # ... existing mounts ...
```

After the next pod restart, HACS will be automatically installed.

### Step 3: Install hass-oidc-auth via HACS

This step requires manual intervention via the Home Assistant UI:

1. In Home Assistant UI, go to **HACS > Integrations > Explore & Download Repositories**
2. Search for "OpenID Connect"
3. Install `hass-oidc-auth`
4. Restart Home Assistant

### Step 4: Update Home Assistant Configuration

Update `kubernetes/main/apps/default/home-assistant/app/configs/configuration.yaml`:

```yaml
# Home Assistant Configuration
# Managed declaratively via GitOps - this file is read-only at runtime

default_config:

frontend:
  themes: !include_dir_merge_named themes

homeassistant:
  packages: !include_dir_named packages

# OIDC Authentication via Authentik
auth_oidc:
  client_id: !env_var HASS_OIDC_CLIENT_ID
  client_secret: !env_var HASS_OIDC_CLIENT_SECRET
  discovery_url: !env_var HASS_OIDC_DISCOVERY_URL
  display_name: "Sign in with Authentik"
  claims:
    display_name: name
    username: preferred_username
    groups: groups
  roles:
    admin: home-assistant-admins
  features:
    automatic_person_creation: true

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

http:
  use_x_forwarded_for: true
  trusted_proxies:
    - !env_var HASS_HTTP_TRUSTED_PROXY_1
    - !env_var HASS_HTTP_TRUSTED_PROXY_2

recorder:
  db_url: !env_var HASS_RECORDER_DB_URL
```

### Step 5: Update Secrets

Update `kubernetes/main/apps/default/home-assistant/app/secret.sops.yaml` to add the discovery URL:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: home-assistant-secret
stringData:
  # Existing secrets...
  HASS_OIDC_CLIENT_ID: "home-assistant"
  HASS_OIDC_CLIENT_SECRET: "YOUR_CLIENT_SECRET"
  # Add discovery URL
  HASS_OIDC_DISCOVERY_URL: "https://sso.${SECRET_DOMAIN}/application/o/home-assistant/.well-known/openid-configuration"
```

**Note**: The `${SECRET_DOMAIN}` substitution won't work inside SOPS-encrypted secrets. Use the actual domain value, or create a ConfigMap for non-sensitive configuration.

**Alternative**: Use a ConfigMap for the discovery URL since it's not sensitive:

Create `kubernetes/main/apps/default/home-assistant/app/oidc-config.yaml`:

```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: home-assistant-oidc-config
data:
  HASS_OIDC_DISCOVERY_URL: "https://sso.${SECRET_DOMAIN}/application/o/home-assistant/.well-known/openid-configuration"
```

Then update the HelmRelease to include this ConfigMap in `envFrom`.

### Step 6: Update HelmRelease

Add the OIDC ConfigMap to the Home Assistant container's `envFrom` in `helmrelease.yaml`:

```yaml
containers:
  app:
    # ... existing config ...
    envFrom:
      - secretRef:
          name: home-assistant-secret
      - configMapRef:
          name: home-assistant-oidc-config  # Add this
```

Also include the HACS installation from Step 2 (either env var or init container).

### Step 7: Update Kustomization

Add the new ConfigMap to `kubernetes/main/apps/default/home-assistant/app/kustomization.yaml`:

```yaml
resources:
  - ./cluster.yaml
  - ./scheduledbackup.yaml
  - ./pvc.yaml
  - ./secret.sops.yaml
  - ./oidc-config.yaml  # Add this
  - ./helmrelease.yaml
  - ./config-volsync-r2.yaml
  - ./config-volsync-r2.sops.yaml
```

### Step 8: Create Authentik Group (Optional RBAC)

If using role-based access control:

1. In Authentik admin, go to **Directory > Groups > Create**
2. Create group `home-assistant-admins`
3. Add users who should have admin access to Home Assistant

## Post-Deployment Checklist

- [ ] HACS auto-installed (via env var or init container)
- [ ] hass-oidc-auth integration installed via HACS (manual step)
- [ ] Authentik provider and application created
- [ ] Configuration.yaml updated with `auth_oidc` block
- [ ] Secrets/ConfigMap deployed with OIDC configuration
- [ ] Home Assistant restarted and healthy
- [ ] OIDC login available at `https://ha.${SECRET_DOMAIN}/auth/oidc/welcome`
- [ ] Login flow redirects to Authentik and returns successfully
- [ ] User created in Home Assistant after first OIDC login
- [ ] Tailscale ingress OIDC callback works (if using)

## Verification Steps

1. **Check integration loaded**:
   ```bash
   kubectl logs -n default deployment/home-assistant -c app | grep -i oidc
   ```

2. **Test login flow**:
   - Navigate to `https://ha.${SECRET_DOMAIN}/auth/oidc/welcome`
   - Should redirect to Authentik login
   - After authentication, should return to Home Assistant

3. **Verify user creation**:
   - In Home Assistant, go to **Settings > People**
   - New OIDC user should appear after first login

## Known Issues & Workarounds

### Issue: hass-oidc-auth is Alpha Software

The integration carries this warning: "This is an alpha release. I give no guarantees about code quality, error handling or security."

**Mitigation**: Keep local auth enabled as fallback. The `homeassistant` auth provider remains active alongside OIDC.

### Issue: hass-oidc-auth Requires Manual HACS Installation

While HACS itself is installed declaratively via `HOME_ASSISTANT__HACS_INSTALL`, the hass-oidc-auth integration must still be installed manually through the HACS UI.

**Workaround**: Document the manual step in runbook. This is a one-time operation that persists in the config PVC.

### Issue: Environment Variable Substitution in !env_var

Home Assistant's `!env_var` directive may not work with all configuration options.

**Workaround**: If `!env_var` doesn't work for certain fields, hardcode values or use Home Assistant's `secrets.yaml` file (less GitOps-friendly).

### Issue: Companion App Authentication

Unlike proxy-based auth (Option 2), native OIDC should work with the companion app since authentication happens at the application layer, not the ingress layer.

**Verification**: Test companion app login after implementation.

## Rollback Plan

If OIDC authentication fails:

1. **Revert configuration.yaml**:
   - Remove `auth_oidc` block
   - Commit and push to trigger Flux reconciliation

2. **Access via local auth**:
   - Local `homeassistant` auth provider remains active
   - Login with original credentials

3. **Uninstall integration** (if needed):
   - Via HACS: Remove hass-oidc-auth integration
   - Restart Home Assistant

## Future Considerations

### Envoy Gateway Migration

This OIDC approach is **ingress-agnostic**. When migrating from nginx-ingress to Envoy Gateway:
- No changes required to OIDC configuration
- Authentication happens at application layer
- Only ingress resources need updating (separate from auth)

### Alternative: Envoy ext_authz

After Envoy Gateway migration, you could optionally switch to proxy-based auth using Authentik's Envoy integration with `SecurityPolicy` CRD. This would provide:
- Centralized auth across multiple applications
- SSO without per-app OIDC configuration

However, this reintroduces the companion app issue requiring split routing.

## Notes

- The discovery URL format for Authentik is: `https://<authentik-domain>/application/o/<app-slug>/.well-known/openid-configuration`
- The callback URL is always: `<home-assistant-url>/auth/oidc/callback`
- Groups scope requires Authentik provider to include the `groups` scope in token
- Consider creating a dedicated Authentik group for admin access rather than granting admin to all OIDC users

## k3s Compatibility

Fully compatible with k3s. No special considerations required.
