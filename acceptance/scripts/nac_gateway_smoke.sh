#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${NAC_BASE_URL:-https://nac-beta.xiaobei.top/}"
PROJECT_ID="${NAC_PROJECT_ID:-e4ebe630-1c26-48d0-8d29-4563375ee959}"
ENVIRONMENT="${NAC_ENVIRONMENT:-hack-8}"
if [ -z "${NAC_AK:-}" ] || [ -z "${NAC_SK:-}" ]; then
  echo "NAC_AK and NAC_SK must be provided by the secure execution environment" >&2
  exit 2
fi
AK="${NAC_AK}"
SK="${NAC_SK}"
PROMPT="${NAC_SMOKE_PROMPT:-请只回复 OK}"

if ! command -v nac >/dev/null 2>&1; then
  echo "NAC CLI not found" >&2
  exit 127
fi

nac --version

if ! nac --version | awk '{print $2}' | grep -Eq '^0\.4\.([1-9][0-9]*|[0-9]+)$|^[1-9][0-9]*\.'; then
  echo "NAC CLI version is too old; expected >= 0.4.1" >&2
  exit 126
fi

export NAC_TOKEN="${AK}:${SK}"
nac chat "${ENVIRONMENT}" \
  --base-url "${BASE_URL}" \
  --project-id "${PROJECT_ID}" \
  -m "${PROMPT}" \
  --json
