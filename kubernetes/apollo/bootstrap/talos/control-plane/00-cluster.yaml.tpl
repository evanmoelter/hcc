cluster:
  allowSchedulingOnControlPlanes: true
  apiServer:
    certSANs:
      - {{ .Data.apiVIP }}
  etcd:
    advertisedSubnets:
      - {{ .Data.nodeSubnet }}
      - "!{{ .Data.apiVIP }}/32"
    extraArgs:
      listen-metrics-urls: http://0.0.0.0:2381
  controllerManager:
    extraArgs:
      bind-address: 0.0.0.0
  scheduler:
    extraArgs:
      bind-address: 0.0.0.0
