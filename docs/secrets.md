# Apollo secrets

Apollo uses External Secrets Operator (ESO) and 1Password Connect in the `security` namespace.
The `onepassword` ClusterSecretStore reads only the dedicated `hcc-apollo` vault. The operator chose
Connect for this migration after reviewing the SDK alternative and its service-account quotas.
ESO's older Connect provider is deprecated upstream; revisit its support when upgrading ESO.

The Flux dependency chain is `kube-prometheus-stack` → `external-secrets` → `onepassword-connect` →
`onepassword-store`. Each Kustomization waits for readiness; the store has an explicit Ready-condition
check. Applications that consume secrets depend on `onepassword-store` and reference the `onepassword`
ClusterSecretStore. Keep each application's ExternalSecret in its app directory.

ESO uses its own certificate controller for its webhook, so cert-manager is not a bootstrap dependency.
Its ServiceMonitor feeds Apollo's existing Prometheus. PushSecret controllers and CRDs are disabled.
The separate 1Password Kubernetes operator is disabled; ESO creates the application Secrets.

Connect's API and sync containers share a 1 GiB disk-backed `emptyDir` cache. Pod replacement discards
that cache and requires a successful resync with 1Password. No Longhorn volume or backup is needed.
Both containers run as UID/GID 999 with read-only root filesystems and dropped capabilities. The pinned
images own `/home/opuser/.op` as 999 with mode 0700, so the usual UID 568 cannot reach the mounted files.
The operator has supplied bootstrap credentials; runtime behavior still needs verification after Flux deploys the release.

Connect is a ClusterIP service. Its NetworkPolicy permits inbound API traffic only from ESO pods in
the same namespace. ESO currently reaches it over HTTP inside the cluster; add internal TLS after
cert-manager is available. No Gateway route or external DNS record exposes Connect.

## Bootstrap credentials

The operator has populated the committed SOPS file. For a new integration or credential rotation,
the operator performs these steps; agents must not access 1Password or decrypt this file.

1. Create the `hcc-apollo` vault and an Apollo-specific Connect integration following the
   [1Password setup guide](https://www.1password.dev/connect/get-started). Grant the integration access
   with read access to `hcc-apollo` and read/write access to `hcc-secrets`, as configured by the operator.
   The current store selects only `hcc-apollo`; write-back to `hcc-secrets` is not configured.
2. Save the integration's credentials JSON and token securely for disaster recovery. They cannot
   depend on ESO for delivery, because they are needed to start the provider ESO reads from.
3. Edit the encrypted file locally:

   ```sh
   sops kubernetes/apollo/apps/security/onepassword-connect/app/secret.sops.yaml
   ```

   Set `stringData.1password-credentials.json` to the **raw JSON**, using a YAML block scalar for
   multiline contents. This chart mounts a file; do not base64-encode the JSON as an environment-based
   Connect setup would require. Set `stringData.token` to the Connect token. Save through SOPS so the
   tracked file remains encrypted. Do not paste either value into chat, logs, or PR descriptions.
4. Commit the encrypted update with these manifests and let Flux deploy it after merge.

SOPS and age continue to deliver bootstrap credentials; existing cluster and Talos secrets remain
unchanged. ESO does not migrate the old cluster's secrets or copy vault items automatically.

After deployment, check readiness without reading any secret values:

```sh
kubectl --context apollo -n security get helmreleases,pods
kubectl --context apollo -n flux-system get kustomization external-secrets onepassword-connect onepassword-store
kubectl --context apollo get clustersecretstore onepassword
```

All three Kustomizations and the store must become Ready. Verify the first consuming ExternalSecret
reports `Ready=True` and `SecretSynced` before treating application secret delivery as proven.

The chart mounts the credentials file with `subPath`. Replacing the credentials JSON later requires
a Connect pod rollout to load it: change a pod annotation in the HelmRelease through git as part of
that credential rotation. A token-only update is read by ESO from the Kubernetes Secret.

## Application pattern

Create one 1Password item per application, with unique field labels matching its secret keys.
The Connect provider uses the item title as `remoteRef.key` and a field label as `remoteRef.property`:

```yaml
# yaml-language-server: $schema=https://k8s-schemas.home-operations.com/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: example
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    creationPolicy: Owner
  data:
    - secretKey: API_TOKEN
      remoteRef:
        key: example
        property: API_TOKEN
```

The OCI chart and readiness layout draws from
[onedr0p](https://github.com/onedr0p/home-ops/tree/main/kubernetes/apps/external-secrets), and the combined
bootstrap Secret follows
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/kube-system/external-secrets/1password/1password.yaml).
Provider details come from [ESO's Connect documentation](https://external-secrets.io/latest/provider/1password-automation/).
