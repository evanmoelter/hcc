apiVersion: v1alpha1
kind: VLANConfig
name: bond0.{{ .Data.iotVlanID }}
parent: bond0
vlanID: {{ .Data.iotVlanID }}
---
machine:
  nodeLabels:
    network.home.arpa/iot-ipv4: "true"
