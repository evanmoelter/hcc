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

Connect is a ClusterIP service. Its NetworkPolicy permits inbound API traffic only from ESO pods in
the same namespace. ESO currently reaches it over HTTP inside the cluster; add internal TLS after
cert-manager is available. No Gateway route or external DNS record exposes Connect.

SOPS supplies Connect's credentials JSON and ESO's Connect token independently of ESO, so the provider
can start before it can serve application secrets. The Connect integration has read access to
`hcc-apollo` and read/write access to `hcc-secrets`. The current store selects only `hcc-apollo`;
write-back to `hcc-secrets` is not configured. Talos and other bootstrap secrets continue to use SOPS
and age.

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

## Configuration reloads

[Reloader](https://github.com/stakater/Reloader#usage) is opt-in. Enable it for workloads that need a restart
when referenced Secrets or ConfigMaps change; leave apps that reload configuration themselves unannotated.

Put `reloader.stakater.com/auto: "true"` on the workload's `metadata.annotations`. In app-template, use
`values.controllers.<controller>.annotations`; in the external-dns chart, use `values.deploymentAnnotations`.
The Connect chart uses `values.connect.annotations`. An annotation on the HelmRelease or pod template
does not opt in the Deployment.

ESO-managed credentials reach pods after ESO refreshes the Secret and Reloader triggers a rollout.
End-to-end rotation verification remains pending.

## References

The OCI chart and readiness layout draws from
[onedr0p](https://github.com/onedr0p/home-ops/tree/main/kubernetes/apps/external-secrets), and the combined
bootstrap Secret follows
[billimek](https://github.com/billimek/k8s-gitops/blob/master/kubernetes/kube-system/external-secrets/1password/1password.yaml).
Provider details come from [ESO's Connect documentation](https://external-secrets.io/latest/provider/1password-automation/).
