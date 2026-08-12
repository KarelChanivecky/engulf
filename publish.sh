#!/usr/bin/env bash

set -euo pipefail

usage() {
    echo "usage: $0 [--repository testpypi|pypi]" >&2
}

repository="testpypi"

if (( $# > 0 )); then
    if (( $# != 2 )) || [[ $1 != "--repository" ]]; then
        usage
        exit 2
    fi
    repository=$2
fi

case "${repository}" in
    testpypi | pypi) ;;
    *)
        usage
        exit 2
        ;;
esac

workspace_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_executable="${workspace_root}/.venv/bin/python"

"${workspace_root}/build.sh"

artifacts=(
    "${workspace_root}/engulf-api/dist/"*
    "${workspace_root}/engulf/dist/"*
    "${workspace_root}/engulf-executable-wrapper-api/dist/"*
    "${workspace_root}/engulf-executable-wrapper/dist/"*
    "${workspace_root}/plugins/engulf-plugin-list/dist/"*
)

"${python_executable}" -m twine upload \
    --repository "${repository}" \
    "${artifacts[@]}"
