#!/usr/bin/env bash

set -euo pipefail

workspace_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_executable="${workspace_root}/.venv/bin/python"

cd -- "${workspace_root}"

if [[ ! -d "${workspace_root}/.venv" ]]; then
    if ! command -v python3.14 >/dev/null 2>&1; then
        echo "error: Python 3.14 is required to create the workspace environment" >&2
        exit 1
    fi

    python3.14 -m venv --upgrade-deps "${workspace_root}/.venv"
    "${python_executable}" -m pip install --group dev
elif [[ ! -x "${python_executable}" ]]; then
    echo "error: ${workspace_root}/.venv is not a usable virtual environment" >&2
    exit 1
fi

packages=(
    engulf-api
    engulf
    engulf-executable-wrapper-api
    engulf-executable-wrapper
    plugins/engulf-plugin-list
)

for package in "${packages[@]}"; do
    "${python_executable}" -m build --no-isolation "${workspace_root}/${package}"
done

artifacts=()
for package in "${packages[@]}"; do
    artifacts+=("${workspace_root}/${package}/dist/"*)
done

"${python_executable}" -m twine check "${artifacts[@]}"
