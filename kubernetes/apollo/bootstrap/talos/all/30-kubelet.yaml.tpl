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
