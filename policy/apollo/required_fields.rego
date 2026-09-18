package main

import rego.v1

helm_release if {
	startswith(input.apiVersion, "helm.toolkit.fluxcd.io/")
	input.kind == "HelmRelease"
}

required_fields contains path if {
	helm_release
	path := [
		["spec", "install", "strategy", "name"],
		["spec", "install", "crds"],
		["spec", "upgrade", "strategy", "name"],
		["spec", "upgrade", "crds"],
		["spec", "upgrade", "cleanupOnFail"],
		["spec", "rollback", "cleanupOnFail"],
	][_]
}

required_fields contains path if {
	helm_release
	some action in ["install", "upgrade"]
	input.spec[action].strategy.name == "RemediateOnFailure"
	path := ["spec", action, "remediation", "retries"]
}

required_fields contains ["spec", "upgrade", "remediation", "remediateLastFailure"] if {
	helm_release
	input.spec.upgrade.strategy.name == "RemediateOnFailure"
}

required_fields contains path if {
	helm_release
	some action in ["install", "upgrade"]
	input.spec[action].strategy.name == "RetryOnFailure"
	path := ["spec", action, "strategy", "retryInterval"]
}

required_fields contains ["spec", "deletionPolicy"] if {
	startswith(input.apiVersion, "kustomize.toolkit.fluxcd.io/")
	input.kind == "Kustomization"
}

configured(resource, path) if {
	value := object.get(resource, path, null)
	value != null
	value != ""
	value != {}
	value != []
}

deny contains msg if {
	some path in required_fields
	not configured(input, path)
	msg := sprintf("%s %s must declare %s", [input.kind, input.metadata.name, concat(".", path)])
}

namespace_pruning_configured if {
	some field in ["annotations", "labels"]
	configured(input, ["metadata", field, "kustomize.toolkit.fluxcd.io/prune"])
}

deny contains msg if {
	input.apiVersion == "v1"
	input.kind == "Namespace"
	not namespace_pruning_configured
	msg := sprintf("Namespace %s must declare the kustomize.toolkit.fluxcd.io/prune annotation or label", [input.metadata.name])
}
