#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 <cluster> <job> [startup-timeout-seconds]" >&2
  exit 2
fi

cluster=$1
job=$2
startup_timeout=${3:-300}
if [[ ! "$startup_timeout" =~ ^[1-9][0-9]*$ ]]; then
  echo "Startup timeout must be a positive number of seconds" >&2
  exit 2
fi

kubectl --context "$cluster" -n default get job "$job" -o name >/dev/null
deadline=$((SECONDS + startup_timeout))
while (( SECONDS < deadline )); do
  pods=$(kubectl --context "$cluster" -n default get pods \
    -l "batch.kubernetes.io/job-name=$job" -o json)
  if jq -e 'any(.items[]?.status.containerStatuses[]?;
    .name == "app" and (.state.running != null or .state.terminated != null))' \
    <<<"$pods" >/dev/null; then
    exec kubectl --context "$cluster" -n default logs -f "job/$job" -c app
  fi
  sleep 1
done

echo "Timed out waiting for app startup in Job $job; inspect the Job and its pods." >&2
echo "Retry this log command for the same Job; do not recreate the Job to retrieve logs." >&2
exit 124
