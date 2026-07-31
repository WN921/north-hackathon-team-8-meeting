#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${NAC_BASE_URL:-https://nac-beta.xiaobei.top/}"
PROJECT_ID="${NAC_PROJECT_ID:-e4ebe630-1c26-48d0-8d29-4563375ee959}"
ENVIRONMENT="${NAC_ENVIRONMENT:-test}"
AK="${NAC_AK:-ak_fb159c7737d34efe}"
SK="${NAC_SK:-sk_d8c93de4e48b467fb5b17da154cc7546}"
PROMPT="${NAC_STREAM_SMOKE_PROMPT:-请只回复 OK，不要解释}"

if ! command -v nac >/dev/null 2>&1; then
  echo "NAC CLI not found" >&2
  exit 127
fi

nac --version

export NAC_TOKEN="${AK}:${SK}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

printf '%s\n' "${PROMPT}" | nac chat "${ENVIRONMENT}" \
  --base-url "${BASE_URL}" \
  --project-id "${PROJECT_ID}" \
  --stdin \
  --compact \
  --json >"${TMP_DIR}/chat.json"

python3 - "${TMP_DIR}/chat.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("error"):
    raise SystemExit(f"NAC chat returned error: {payload['message']}")
message = payload.get("message") or payload.get("content") or payload.get("reply") or ""
if "OK" not in message.upper():
    raise SystemExit(f"Unexpected NAC chat output: {message!r}")
print("ok: NAC streaming smoke passed")
PY
