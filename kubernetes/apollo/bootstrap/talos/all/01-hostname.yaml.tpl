# topf's base config sets `auto: stable`, which Talos rejects alongside a static
# hostname, so replace the document rather than merging into it.
apiVersion: v1alpha1
kind: HostnameConfig
$patch: delete
---
apiVersion: v1alpha1
kind: HostnameConfig
hostname: {{ .Node.Host }}
