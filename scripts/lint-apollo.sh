#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cluster_dir=${1:?Usage: lint-apollo.sh path/to/kubernetes/apollo}

if [[ "$(basename -- "$cluster_dir")" != apollo ]]; then
    echo "Apollo policies only apply to the apollo cluster" >&2
    exit 1
fi

for directory in apps flux components; do
    test -d "$cluster_dir/$directory"
done

files=()
while IFS= read -r -d '' file; do
    files+=("$file")
done < <(find "$cluster_dir/apps" "$cluster_dir/flux" "$cluster_dir/components" \
    -type f \( -name '*.yaml' -o -name '*.yml' \) \
    ! -name '*.sops.yaml' ! -name '*.sops.yml' -print0)

if [[ ${#files[@]} -eq 0 ]]; then
    echo "No Apollo manifests found" >&2
    exit 1
fi

conftest test --policy "$repo_dir/policy/apollo" --parser yaml "${files[@]}"
