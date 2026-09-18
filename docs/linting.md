# Kubernetes linting

Run Apollo's policies and policy tests:

```sh
task kubernetes:lint CLUSTER=apollo
```

The [Rego policies](../policy/apollo/required_fields.rego) define the rules and exceptions;
their [tests](../policy/apollo/required_fields_test.rego) provide accepted and rejected examples.
CI runs the same task under the `Kubeconform Success` check.

Lint checks source manifests before Flux patches. Use kubeconform for schema validation and review the
rendered Flux diff for effective configuration. These checks do not exercise live failure or deletion behavior.
