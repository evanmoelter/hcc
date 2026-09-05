apiVersion: v1alpha1
kind: LinkAliasConfig
name: ethSel0
selector:
  match: glob("{{ .Node.Data.macAddr }}", mac(link.permanent_addr))
---
apiVersion: v1alpha1
kind: BondConfig
name: bond0
links:
  - ethSel0
bondMode: active-backup
addresses:
  - address: {{ .Node.IP }}/{{ .Data.linkPrefixLength }}
routes:
  - gateway: {{ .Data.gateway }}
{{- if eq .Node.Role "control-plane" }}
---
apiVersion: v1alpha1
kind: Layer2VIPConfig
name: {{ .Data.apiVIP }}
link: bond0
{{- end }}
---
apiVersion: v1alpha1
kind: ResolverConfig
nameservers:
  - address: {{ .Data.gateway }}
