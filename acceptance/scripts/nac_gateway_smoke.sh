#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${NAC_BASE_URL:-https://nac-beta.xiaobei.top/}"
PROJECT_ID="${NAC_PROJECT_ID:-e4ebe630-1c26-48d0-8d29-4563375ee959}"
ENVIRONMENT="${NAC_ENVIRONMENT:-hack-8}"
AK="${NAC_AK:-ak_fb159c7737d34efe}"
SK="${NAC_SK:-sk_d8c93de4e48b467fb5b17da154cc7546}"
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
