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
      auto-compaction-mode: periodic
      auto-compaction-retention: "1h"
  controllerManager:
    extraArgs:
      bind-address: 0.0.0.0
  scheduler:
    extraArgs:
      bind-address: 0.0.0.0
    config:
      apiVersion: kubescheduler.config.k8s.io/v1
      kind: KubeSchedulerConfiguration
      profiles:
        - schedulerName: default-scheduler
          plugins:
            score:
              disabled:
                - name: ImageLocality
          pluginConfig:
            - name: PodTopologySpread
              args:
                defaultingType: List
                defaultConstraints:
                  - maxSkew: 1
                    topologyKey: kubernetes.io/hostname
                    whenUnsatisfiable: ScheduleAnyway
