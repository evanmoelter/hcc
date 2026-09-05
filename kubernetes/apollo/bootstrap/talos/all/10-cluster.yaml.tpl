machine:
  certSANs:
    - {{ .Data.apiVIP }}
cluster:
  network:
    cni:
      name: none
    podSubnets: ["10.42.0.0/16"]
    serviceSubnets: ["10.43.0.0/16"]
  proxy:
    disabled: true
  discovery:
    enabled: true
    registries:
      kubernetes:
        disabled: true
      service:
        disabled: false
