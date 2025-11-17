#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export UPSTREAM_GITLAB_BASE_URL="${UPSTREAM_GITLAB_BASE_URL:-https://gitlab.com}"

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Environment variable ${name} is required" >&2
    exit 1
  fi
}

copilot_login() {
  require_env COPILOT_ACCESS_TOKEN
  eval "$(github-copilot-cli alias -- bash)"
  echo "${COPILOT_ACCESS_TOKEN}" | github-copilot-cli auth login --token-stdin >/dev/null
}
