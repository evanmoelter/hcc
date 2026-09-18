package main_test

import data.main
import rego.v1

release := {
	"apiVersion": "helm.toolkit.fluxcd.io/v2",
	"kind": "HelmRelease",
	"metadata": {"name": "example"},
	"spec": {
		"install": {
			"strategy": {"name": "RemediateOnFailure"},
			"crds": "Skip",
			"remediation": {"retries": 0},
		},
		"upgrade": {
			"strategy": {"name": "RemediateOnFailure"},
			"crds": "Create",
			"cleanupOnFail": false,
			"remediation": {"retries": -1, "remediateLastFailure": false},
		},
		"rollback": {"cleanupOnFail": false},
	},
}

release_fields := [
	["spec", "install", "strategy", "name"],
	["spec", "install", "remediation", "retries"],
	["spec", "upgrade", "strategy", "name"],
	["spec", "upgrade", "cleanupOnFail"],
	["spec", "upgrade", "remediation", "retries"],
	["spec", "upgrade", "remediation", "remediateLastFailure"],
	["spec", "rollback", "cleanupOnFail"],
]

test_explicit_nondefault_values_pass if {
	count(main.deny) == 0 with input as release
}

test_crd_policies_are_optional if {
	resource := json.remove(release, [["spec", "install", "crds"], ["spec", "upgrade", "crds"]])
	count(main.deny) == 0 with input as resource
}

test_uninstall_remediation_without_rollback_passes if {
	resource := json.patch(release, [
		{"op": "add", "path": "/spec/upgrade/remediation/strategy", "value": "uninstall"},
		{"op": "remove", "path": "/spec/rollback"},
	])
	count(main.deny) == 0 with input as resource
}

test_explicit_rollback_remediation_requires_cleanup if {
	resource := json.patch(release, [
		{"op": "add", "path": "/spec/upgrade/remediation/strategy", "value": "rollback"},
		{"op": "remove", "path": "/spec/rollback"},
	])
	failures := main.deny with input as resource
	"HelmRelease example must declare spec.rollback.cleanupOnFail" in failures
}

test_each_missing_release_field_fails if {
	every path in release_fields {
		resource := json.remove(release, [path])
		failures := main.deny with input as resource
		sprintf("HelmRelease example must declare %s", [concat(".", path)]) in failures
	}
}

test_null_and_empty_fields_fail if {
	every path in release_fields {
		every value in [null, "", {}, []] {
			resource := json.patch(release, [{"op": "replace", "path": path, "value": value}])
			failures := main.deny with input as resource
			sprintf("HelmRelease example must declare %s", [concat(".", path)]) in failures
		}
	}
}

test_missing_parent_blocks_fail if {
	every path in [["spec"], ["spec", "install"], ["spec", "upgrade"], ["spec", "rollback"]] {
		resource := json.remove(release, [path])
		count(main.deny) > 0 with input as resource
	}
}

retry_release := json.patch(release, [
	{"op": "replace", "path": "/spec/install/strategy", "value": {"name": "RetryOnFailure", "retryInterval": "10m"}},
	{"op": "replace", "path": "/spec/upgrade/strategy", "value": {"name": "RetryOnFailure", "retryInterval": "2m"}},
	{"op": "remove", "path": "/spec/install/remediation"},
	{"op": "remove", "path": "/spec/upgrade/remediation"},
	{"op": "remove", "path": "/spec/rollback"},
])

test_retry_strategy_without_remediation_passes if {
	count(main.deny) == 0 with input as retry_release
}

test_retry_strategy_requires_interval if {
	every action in ["install", "upgrade"] {
		resource := json.remove(retry_release, [["spec", action, "strategy", "retryInterval"]])
		count(main.deny) == 1 with input as resource
	}
}

test_deletion_policy_choices_pass if {
	every value in ["Orphan", "Delete", "MirrorPrune", "WaitForTermination"] {
		resource := {
			"apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
			"metadata": {"name": "example"}, "spec": {"prune": true, "deletionPolicy": value},
		}
		count(main.deny) == 0 with input as resource
	}
}

test_missing_deletion_policy_fails if {
	resource := {
		"apiVersion": "kustomize.toolkit.fluxcd.io/v1", "kind": "Kustomization",
		"metadata": {"name": "example"}, "spec": {"prune": false},
	}
	count(main.deny) == 1 with input as resource
}

kustomization := {
	"apiVersion": "kustomize.toolkit.fluxcd.io/v1",
	"kind": "Kustomization",
	"metadata": {"name": "example"},
	"spec": {"prune": false, "deletionPolicy": "Orphan"},
}

test_retention_policies_without_pruning_pass if {
	every policy in ["Orphan", "MirrorPrune"] {
		resource := json.patch(kustomization, [{"op": "replace", "path": "/spec/deletionPolicy", "value": policy}])
		count(main.deny) == 0 with input as resource
	}
}

test_deletion_without_pruning_requires_explanation if {
	every policy in ["Delete", "WaitForTermination"] {
		resource := json.patch(kustomization, [{"op": "replace", "path": "/spec/deletionPolicy", "value": policy}])
		failures := main.deny with input as resource
		count(failures) == 1
		some msg in failures
		contains(msg, "requires a nonblank lint.flux.home.arpa/delete-without-prune-reason annotation")
	}
}

test_explained_deletion_without_pruning_passes if {
	every policy in ["Delete", "WaitForTermination"] {
		resource := json.patch(kustomization, [
			{"op": "replace", "path": "/spec/deletionPolicy", "value": policy},
			{"op": "add", "path": "/metadata/annotations", "value": {
				"lint.flux.home.arpa/delete-without-prune-reason": "Keep removed resources until the owner is deleted.",
			}},
		])
		count(main.deny) == 0 with input as resource
	}
}

test_invalid_deletion_explanations_fail if {
	every policy in ["Delete", "WaitForTermination"] {
		every reason in [null, "", " \t\n", false, true, 0, [], {}] {
			resource := json.patch(kustomization, [
				{"op": "replace", "path": "/spec/deletionPolicy", "value": policy},
				{"op": "add", "path": "/metadata/annotations", "value": {
					"lint.flux.home.arpa/delete-without-prune-reason": reason,
				}},
			])
			count(main.deny) == 1 with input as resource
		}
	}
}

test_deletion_exception_does_not_bypass_required_fields if {
	resource := json.patch(kustomization, [
		{"op": "remove", "path": "/spec/deletionPolicy"},
		{"op": "add", "path": "/metadata/annotations", "value": {
			"lint.flux.home.arpa/delete-without-prune-reason": "Keep removed resources until the owner is deleted.",
		}},
	])
	failures := main.deny with input as resource
	"Kustomization example must declare spec.deletionPolicy" in failures
}

test_namespace_annotation_or_label_passes if {
	every field in ["annotations", "labels"] {
		every value in ["enabled", "disabled"] {
			resource := {"apiVersion": "v1", "kind": "Namespace", "metadata": {
				"name": "example", field: {"kustomize.toolkit.fluxcd.io/prune": value},
			}}
			count(main.deny) == 0 with input as resource
		}
	}
}

test_missing_namespace_pruning_fails if {
	resource := {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "example"}}
	count(main.deny) == 1 with input as resource
}

test_other_resources_ignored if {
	every resource in [
		{"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization"},
		{"apiVersion": "v1", "kind": "ConfigMap"},
		null,
	] {
		count(main.deny) == 0 with input as resource
	}
}

test_opt_out_label_does_not_bypass_required_fields if {
	resource := {
		"apiVersion": "helm.toolkit.fluxcd.io/v2", "kind": "HelmRelease",
		"metadata": {"name": "example", "labels": {"helm-defaults.flux.home.arpa/disabled": "true"}},
	}
	count(main.deny) > 0 with input as resource
}
