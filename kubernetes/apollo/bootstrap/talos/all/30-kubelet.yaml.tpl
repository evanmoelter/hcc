machine:
  kubelet:
    nodeIP:
      validSubnets:
        - {{ .Data.nodeSubnet }}
        - "!{{ .Data.apiVIP }}/32"
    extraMounts:
      - destination: /var/mnt/longhorn
        type: bind
        source: /var/mnt/longhorn
        options: ["bind", "rshared", "rw"]
    extraConfig:
      serializeImagePulls: false
      maxParallelImagePulls: 3
      imageGCHighThresholdPercent: 70
      imageGCLowThresholdPercent: 50
      imageMaximumGCAge: 168h
      shutdownGracePeriod: 90s
      shutdownGracePeriodCriticalPods: 60s
