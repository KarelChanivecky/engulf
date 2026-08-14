#!/usr/bin/env bash

set -euo pipefail

workspace_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec make --directory "${workspace_root}" build
