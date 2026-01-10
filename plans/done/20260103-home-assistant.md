# Plan: Add Home Assistant to Cluster

## Overview

Deploy Home Assistant to the cluster with:
- Code-server sidecar for config editing
- Co-located CNPG PostgreSQL cluster in the default namespace
- Node affinity to hcc3 (for future USB device passthrough)
- Internal ingress at `ha.${SECRET_DOMAIN}`
- Tailscale endpoint for remote access
- Authentik SSO integration
- R2 backup for the database

## Prerequisites

- **Multus CNI**: Required for IoT network access (mDNS, device discovery). See `20260103-multus-cni-prerequisite.md`. Deploy Multus first, then add the IoT network annotation to the Home Assistant HelmRelease.

## Dependencies

| Dependency | Purpose |
|------------|---------|
| cloudnative-pg (operator) | PostgreSQL operator for the co-located cluster |
| longhorn | Storage for config PVC and database |
| tailscale-operator | Tailscale ingress |
| ingress-nginx-internal | Internal ingress |
| authentik | SSO authentication |

## Architecture

```
default namespace
├── home-assistant (HelmRelease - app-template 4.5.0)
│   ├── home-assistant controller
│   │   ├── app container (ghcr.io/home-operations/home-assistant)
│   │   └── code-server sidecar (ghcr.io/coder/code-server)
│   ├── service: home-assistant (port 8123)
│   ├── service: code-server (port 8080)
│   ├── ingress: internal (ha.${SECRET_DOMAIN})
│   ├── ingress: tailscale (home-assistant)
│   └── ingress: code-server internal (ha-code.${SECRET_DOMAIN})
├── home-assistant-pg (CNPG Cluster)
│   └── home-assistant database (initdb managed)
├── home-assistant-pg-scheduledbackup (ScheduledBackup)
└── home-assistant-config (PVC - 5Gi)
```

## Directory Structure

```
kubernetes/main/apps/default/home-assistant/
├── ks.yaml                           # Flux Kustomization
└── app/
    ├── kustomization.yaml
    ├── helmrelease.yaml              # app-template 4.5.0
    ├── secret.sops.yaml              # DB creds, Authentik OIDC
    ├── pvc.yaml                      # 5Gi config storage
    ├── cluster.yaml                  # Co-located CNPG cluster
    ├── scheduledbackup.yaml          # Daily R2 backup
    └── config-volsync-r2.yaml        # Optional: config backup
    └── config-volsync-r2.sops.yaml   # Volsync R2 credentials
```

## Implementation Steps

### Step 1: Create Directory Structure

```bash
mkdir -p kubernetes/main/apps/default/home-assistant/app
```

### Step 2: Create Flux Kustomization

Create `kubernetes/main/apps/default/home-assistant/ks.yaml`:

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app home-assistant
  namespace: flux-system
spec:
  targetNamespace: default
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  dependsOn:
    - name: cloudnative-pg
    - name: longhorn
    - name: authentik
  path: ./kubernetes/main/apps/default/home-assistant/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: true
  interval: 30m
  retryInterval: 1m
  timeout: 5m
  postBuild:
    substitute:
      APP: *app
```

### Step 3: Create App Kustomization

Create `kubernetes/main/apps/default/home-assistant/app/kustomization.yaml`:

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./cluster.yaml
  - ./scheduledbackup.yaml
  - ./pvc.yaml
  - ./secret.sops.yaml
  - ./helmrelease.yaml
  - ./config-volsync-r2.yaml
  - ./config-volsync-r2.sops.yaml
```

### Step 4: Create CNPG Cluster

Create `kubernetes/main/apps/default/home-assistant/app/cluster.yaml`:

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/postgresql.cnpg.io/cluster_v1.json
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: home-assistant-pg
  namespace: default
spec:
  instances: 1
  imageName: ghcr.io/cloudnative-pg/postgresql:17.2-1
  primaryUpdateStrategy: unsupervised

  storage:
    size: 5Gi
    storageClass: longhorn

  enableSuperuserAccess: true
  superuserSecret:
    name: home-assistant-pg-secret

  postgresql:
    parameters:
      max_connections: "100"
      shared_buffers: 128MB

  # Bootstrap with initdb - creates database and owner automatically
  bootstrap:
    initdb:
      database: home_assistant
      owner: home_assistant
      secret:
        name: home-assistant-pg-secret

  backup:
    retentionPolicy: 30d
    barmanObjectStore:
      data:
        compression: bzip2
      wal:
        compression: bzip2
        maxParallel: 4
      destinationPath: s3://tf-hcc-cloudnativepg/
      endpointURL: https://${SECRET_CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com
      serverName: home-assistant-pg-v1
      s3Credentials:
        accessKeyId:
          name: home-assistant-pg-secret
          key: R2_ACCESS_KEY_ID
        secretAccessKey:
          name: home-assistant-pg-secret
          key: R2_SECRET_ACCESS_KEY
```

### Step 5: Create Scheduled Backup

Create `kubernetes/main/apps/default/home-assistant/app/scheduledbackup.yaml`:

```yaml
---
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: home-assistant-pg
  namespace: default
spec:
  schedule: "@daily"
  immediate: true
  backupOwnerReference: self
  cluster:
    name: home-assistant-pg
```

### Step 6: Create PVC

Create `kubernetes/main/apps/default/home-assistant/app/pvc.yaml`:

```yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: home-assistant-config
  namespace: default
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: longhorn
  resources:
    requests:
      storage: 5Gi
```

### Step 7: Create Secrets

Create `kubernetes/main/apps/default/home-assistant/app/secret.sops.yaml`:

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: home-assistant-secret
  namespace: default
stringData:
  # Home Assistant secrets
  HASS_LATITUDE: "YOUR_LATITUDE"
  HASS_LONGITUDE: "YOUR_LONGITUDE"
  HASS_ELEVATION: "YOUR_ELEVATION"
  # Database connection (uses CNPG service)
  HASS_RECORDER_DB_URL: "postgresql://home_assistant:PASSWORD@home-assistant-pg-rw.default.svc.cluster.local:5432/home_assistant"
  # Authentik OIDC
  HASS_OIDC_CLIENT_ID: "home-assistant"
  HASS_OIDC_CLIENT_SECRET: "YOUR_CLIENT_SECRET"
---
apiVersion: v1
kind: Secret
metadata:
  name: home-assistant-pg-secret
  namespace: default
stringData:
  # CNPG superuser
  username: postgres
  password: "GENERATE_SECURE_PASSWORD"
  # App user (for initdb)
  POSTGRES_USER: home_assistant
  POSTGRES_PASSWORD: "GENERATE_SECURE_PASSWORD"
  # R2 backup credentials
  R2_ACCESS_KEY_ID: "YOUR_R2_ACCESS_KEY"
  R2_SECRET_ACCESS_KEY: "YOUR_R2_SECRET_KEY"
```

**Note**: Encrypt with SOPS before committing:
```bash
sops -e -i kubernetes/main/apps/default/home-assistant/app/secret.sops.yaml
```

### Step 8: Create HelmRelease

Create `kubernetes/main/apps/default/home-assistant/app/helmrelease.yaml`:

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/bjw-s/helm-charts/app-template-4.5.0/charts/other/app-template/schemas/helmrelease-helm-v2.schema.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app home-assistant
  namespace: default
spec:
  interval: 30m
  chart:
    spec:
      chart: app-template
      version: 4.5.0
      sourceRef:
        kind: HelmRepository
        name: bjw-s
        namespace: flux-system

  values:
    controllers:
      home-assistant:
        annotations:
          reloader.stakater.com/auto: "true"

        pod:
          # Pin to hcc3 for USB device access
          nodeSelector:
            kubernetes.io/hostname: hcc3
          securityContext:
            runAsUser: 568
            runAsGroup: 568
            runAsNonRoot: true
            fsGroup: 568
            fsGroupChangePolicy: OnRootMismatch

        containers:
          app:
            image:
              repository: ghcr.io/home-operations/home-assistant
              tag: 2025.12.5
            env:
              TZ: ${TIMEZONE}
              # Trusted proxies for ingress
              HASS_HTTP_TRUSTED_PROXY_1: 10.42.0.0/16
              HASS_HTTP_TRUSTED_PROXY_2: 10.43.0.0/16
            envFrom:
              - secretRef:
                  name: home-assistant-secret
            probes:
              liveness:
                enabled: true
              readiness:
                enabled: true
              startup:
                enabled: true
                spec:
                  failureThreshold: 30
                  periodSeconds: 5
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities:
                drop: ["ALL"]
            resources:
              requests:
                cpu: 10m
                memory: 512Mi
              limits:
                memory: 2Gi

          code-server:
            image:
              repository: ghcr.io/coder/code-server
              tag: 4.107.0
            args:
              - --auth
              - none
              - --disable-telemetry
              - --disable-update-check
              - --user-data-dir
              - /config/.vscode
              - --extensions-dir
              - /config/.vscode/extensions
              - --port
              - "8080"
              - /config
            env:
              TZ: ${TIMEZONE}
            resources:
              requests:
                cpu: 10m
                memory: 128Mi
              limits:
                memory: 1Gi

    service:
      app:
        controller: home-assistant
        ports:
          http:
            port: 8123
      code-server:
        controller: home-assistant
        ports:
          http:
            port: 8080

    ingress:
      app:
        className: internal
        hosts:
          - host: &host ha.${SECRET_DOMAIN}
            paths:
              - path: /
                service:
                  identifier: app
                  port: http
        tls:
          - hosts:
              - *host

      tailscale:
        enabled: true
        className: tailscale
        defaultBackend:
          service:
            name: *app
            port:
              name: http
        tls:
          - hosts:
              - *app

      code-server:
        className: internal
        hosts:
          - host: &codeHost ha-code.${SECRET_DOMAIN}
            paths:
              - path: /
                service:
                  identifier: code-server
                  port: http
        tls:
          - hosts:
              - *codeHost

    persistence:
      config:
        enabled: true
        existingClaim: home-assistant-config
        advancedMounts:
          home-assistant:
            app:
              - path: /config
            code-server:
              - path: /config
      tmp:
        type: emptyDir
        advancedMounts:
          home-assistant:
            app:
              - path: /tmp
                subPath: hass-tmp
            code-server:
              - path: /tmp
                subPath: code-tmp
      cache:
        type: emptyDir
        advancedMounts:
          home-assistant:
            code-server:
              - path: /root/.cache
                subPath: cache
              - path: /root/.local
                subPath: local
```

### Step 9: Create Volsync Backup for Config (Optional)

Create `kubernetes/main/apps/default/home-assistant/app/config-volsync-r2.yaml`:

```yaml
---
apiVersion: volsync.backube/v1alpha1
kind: ReplicationSource
metadata:
  name: home-assistant-config-r2
  namespace: default
spec:
  sourcePVC: home-assistant-config
  trigger:
    schedule: "0 2 * * *"
  restic:
    copyMethod: Snapshot
    pruneIntervalDays: 7
    repository: home-assistant-config-volsync-r2
    volumeSnapshotClassName: longhorn-snapclass
    cacheCapacity: 2Gi
    cacheStorageClassName: longhorn-cache
    cacheAccessModes: ["ReadWriteOnce"]
    storageClassName: longhorn-snapshot
    accessModes: ["ReadWriteOnce"]
    moverSecurityContext:
      runAsUser: 568
      runAsGroup: 568
      fsGroup: 568
    retain:
      daily: 7
      weekly: 4
      monthly: 6
```

Create `kubernetes/main/apps/default/home-assistant/app/config-volsync-r2.sops.yaml`:

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: home-assistant-config-volsync-r2
  namespace: default
stringData:
  RESTIC_REPOSITORY: "s3:https://ACCOUNT_ID.r2.cloudflarestorage.com/BUCKET/home-assistant-config"
  RESTIC_PASSWORD: "GENERATE_SECURE_PASSWORD"
  AWS_ACCESS_KEY_ID: "YOUR_R2_ACCESS_KEY"
  AWS_SECRET_ACCESS_KEY: "YOUR_R2_SECRET_KEY"
```

### Step 10: Configure Authentik OIDC Provider

In Authentik admin:

1. **Create OAuth2/OpenID Provider**:
   - Name: `Home Assistant`
   - Authorization flow: `default-provider-authorization-implicit-consent`
   - Client ID: `home-assistant` (or generate)
   - Client Secret: Generate and save for secret.sops.yaml
   - Redirect URIs:
     - `https://ha.${SECRET_DOMAIN}/auth/oidc/callback`
     - `https://home-assistant.${SECRET_TAILSCALE_DOMAIN}/auth/oidc/callback`
   - Scopes: `openid`, `profile`, `email`

2. **Create Application**:
   - Name: `Home Assistant`
   - Slug: `home-assistant`
   - Provider: Select the provider created above

### Step 11: Configure Home Assistant for OIDC

After initial deployment, add to `/config/configuration.yaml`:

```yaml
homeassistant:
  auth_providers:
    - type: homeassistant
    - type: openid_connect
      client_id: !env_var HASS_OIDC_CLIENT_ID
      client_secret: !env_var HASS_OIDC_CLIENT_SECRET
      authorization_url: https://sso.${SECRET_DOMAIN}/application/o/authorize/
      token_url: https://sso.${SECRET_DOMAIN}/application/o/token/
      userinfo_url: https://sso.${SECRET_DOMAIN}/application/o/userinfo/
      name: Authentik

recorder:
  db_url: !env_var HASS_RECORDER_DB_URL
  purge_keep_days: 30
  commit_interval: 1

http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 10.42.0.0/16
    - 10.43.0.0/16
```

### Step 12: Register with apps Kustomization

Add to `kubernetes/main/apps/default/kustomization.yaml`:

```yaml
resources:
  # ... existing resources
  - ./home-assistant/ks.yaml
```

## Post-Deployment Checklist

- [ ] CNPG cluster is healthy: `kubectl get cluster home-assistant-pg -n default`
- [ ] Home Assistant pod is running on hcc3
- [ ] Internal ingress works at `https://ha.${SECRET_DOMAIN}`
- [ ] Tailscale ingress works at `https://home-assistant.${SECRET_TAILSCALE_DOMAIN}`
- [ ] Code-server accessible at `https://ha-code.${SECRET_DOMAIN}`
- [ ] Database connection working (check recorder in HA logs)
- [ ] Authentik SSO login works
- [ ] Scheduled backup runs: `kubectl get backup -n default`
- [ ] Volsync backup runs (if configured)

## Follow-on Plans

1. **Multus CNI Setup** (prerequisite for IoT network) - see `20260103-multus-cni-prerequisite.md`
   - Install Multus CNI
   - Create NetworkAttachmentDefinition for IoT network
   - After Multus is deployed, add IoT network annotation to Home Assistant:
     ```yaml
     controllers:
       home-assistant:
         pod:
           annotations:
             k8s.v1.cni.cncf.io/networks: |
               [{
                 "name": "iot",
                 "namespace": "kube-system",
                 "ips": ["192.168.x.100/24"]
               }]
     ```

2. **USB Device Passthrough**
   - Z-Wave radio (e.g., Zooz ZST39)
   - Thread/Matter radio (e.g., SkyConnect)
   - Requires privileged container or device plugin

## Rollback Plan

If deployment fails:

1. Delete the Flux Kustomization:
   ```bash
   kubectl delete kustomization home-assistant -n flux-system
   ```

2. Clean up resources:
   ```bash
   kubectl delete cluster home-assistant-pg -n default
   kubectl delete pvc home-assistant-config -n default
   kubectl delete secret home-assistant-secret home-assistant-pg-secret -n default
   ```

3. Remove directory and re-commit

## Notes

- The `ghcr.io/home-operations/home-assistant` image is a community-maintained image optimized for Kubernetes (non-root, proper signal handling)
- Code-server runs as a sidecar sharing the config volume, allowing live editing
- The CNPG cluster uses `initdb` to create the database and owner, avoiding the need for an init container
- Node selector pins the pod to hcc3 for future USB device passthrough
- Both internal and Tailscale ingress are configured for flexible access

## k3s Compatibility

Fully compatible with k3s. No special considerations required.
