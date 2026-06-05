#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_BIN="${OPENCLAW_BIN:-openclaw}"
EXPECTED_OPENCLAW_VERSION="${EXPECTED_OPENCLAW_VERSION:-OpenClaw 2026.3.13 (61d171a)}"
OPENCLAW_GATEWAY_TIMEOUT_MS="${OPENCLAW_GATEWAY_TIMEOUT_MS:-5000}"

if ! command -v "$OPENCLAW_BIN" >/dev/null 2>&1; then
  echo "openclaw binary not found: $OPENCLAW_BIN" >&2
  exit 2
fi

capture() {
  local label="$1"
  shift
  echo "== $label =="
  "$@"
  echo
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local label="$3"
  if ! grep -Fq -- "$needle" <<<"$haystack"; then
    echo "missing expected OpenClaw CLI contract token in $label: $needle" >&2
    exit 1
  fi
}

run_rpc_check() {
  local label="$1"
  shift
  if "$@" >/tmp/openclaw-contract-check.out 2>&1; then
    echo "$label: OK"
    rm -f /tmp/openclaw-contract-check.out
    return 0
  fi
  echo "$label: FAILED" >&2
  if [[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
    cat /tmp/openclaw-contract-check.out >&2
  else
    echo "output suppressed because OPENCLAW_GATEWAY_TOKEN is set" >&2
  fi
  rm -f /tmp/openclaw-contract-check.out
  exit 1
}

version="$("$OPENCLAW_BIN" --version)"
echo "== openclaw version =="
echo "$version"
if [[ "$version" != "$EXPECTED_OPENCLAW_VERSION" ]]; then
  echo "unexpected OpenClaw version; expected: $EXPECTED_OPENCLAW_VERSION" >&2
  exit 1
fi
echo

top_help="$("$OPENCLAW_BIN" --help)"
gateway_help="$("$OPENCLAW_BIN" gateway --help)"
gateway_call_help="$("$OPENCLAW_BIN" gateway call --help)"
gateway_status_help="$("$OPENCLAW_BIN" gateway status --help)"
gateway_probe_help="$("$OPENCLAW_BIN" gateway probe --help)"
gateway_run_help="$("$OPENCLAW_BIN" gateway run --help)"
doctor_help="$("$OPENCLAW_BIN" doctor --help)"
health_help="$("$OPENCLAW_BIN" health --help)"
status_help="$("$OPENCLAW_BIN" status --help)"
agent_help="$("$OPENCLAW_BIN" agent --help)"

assert_contains "$top_help" "gateway *" "openclaw --help"
assert_contains "$top_help" "agent" "openclaw --help"
assert_contains "$top_help" "health" "openclaw --help"
assert_contains "$top_help" "status" "openclaw --help"
assert_contains "$gateway_help" "call" "openclaw gateway --help"
assert_contains "$gateway_help" "probe" "openclaw gateway --help"
assert_contains "$gateway_help" "run" "openclaw gateway --help"
assert_contains "$gateway_help" "status" "openclaw gateway --help"
assert_contains "$gateway_help" "--auth <mode>" "openclaw gateway --help"
assert_contains "$gateway_help" "--bind <mode>" "openclaw gateway --help"
assert_contains "$gateway_help" "--token <token>" "openclaw gateway --help"
assert_contains "$gateway_call_help" "gateway call [options] <method>" "openclaw gateway call --help"
assert_contains "$gateway_call_help" "health/status/system-presence/cron.*" "openclaw gateway call --help"
assert_contains "$gateway_call_help" "--url <url>" "openclaw gateway call --help"
assert_contains "$gateway_call_help" "--token <token>" "openclaw gateway call --help"
assert_contains "$gateway_status_help" "--require-rpc" "openclaw gateway status --help"
assert_contains "$gateway_probe_help" "--url <url>" "openclaw gateway probe --help"
assert_contains "$gateway_run_help" "--force" "openclaw gateway run --help"
assert_contains "$doctor_help" "--non-interactive" "openclaw doctor --help"
assert_contains "$doctor_help" "--generate-gateway-token" "openclaw doctor --help"
assert_contains "$health_help" "--json" "openclaw health --help"
assert_contains "$status_help" "--json" "openclaw status --help"
assert_contains "$agent_help" "--session-id <id>" "openclaw agent --help"
assert_contains "$agent_help" "--json" "openclaw agent --help"

if grep -Fq -- "--lint" <<<"$doctor_help" || grep -Fq -- "--json" <<<"$doctor_help"; then
  echo "doctor unexpectedly exposes --lint or --json; update the contract docs before deploying" >&2
  exit 1
fi

capture "openclaw gateway call --help" "$OPENCLAW_BIN" gateway call --help
capture "openclaw gateway status --help" "$OPENCLAW_BIN" gateway status --help
capture "openclaw gateway probe --help" "$OPENCLAW_BIN" gateway probe --help

echo "OpenClaw CLI contract check: OK"

if [[ -n "${OPENCLAW_GATEWAY_URL:-}" ]]; then
  token_args=()
  if [[ -n "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
    token_args=(--token "$OPENCLAW_GATEWAY_TOKEN")
  fi

  echo "== OpenClaw Gateway RPC checks =="
  echo "gateway URL is configured; token value will not be printed"
  run_rpc_check "gateway status RPC" \
    "$OPENCLAW_BIN" gateway status --json --require-rpc --url "$OPENCLAW_GATEWAY_URL" \
    --timeout "$OPENCLAW_GATEWAY_TIMEOUT_MS" "${token_args[@]}"
  run_rpc_check "gateway probe RPC" \
    "$OPENCLAW_BIN" gateway probe --json --url "$OPENCLAW_GATEWAY_URL" \
    --timeout "$OPENCLAW_GATEWAY_TIMEOUT_MS" "${token_args[@]}"
  run_rpc_check "gateway call health" \
    "$OPENCLAW_BIN" gateway call health --json --url "$OPENCLAW_GATEWAY_URL" \
    --timeout "$OPENCLAW_GATEWAY_TIMEOUT_MS" "${token_args[@]}"
  run_rpc_check "gateway call status" \
    "$OPENCLAW_BIN" gateway call status --json --url "$OPENCLAW_GATEWAY_URL" \
    --timeout "$OPENCLAW_GATEWAY_TIMEOUT_MS" "${token_args[@]}"

  if [[ -n "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
    if "$OPENCLAW_BIN" gateway call health --json --url "$OPENCLAW_GATEWAY_URL" \
      --timeout "$OPENCLAW_GATEWAY_TIMEOUT_MS" --token "__wrong_openclaw_contract_token__" \
      >/tmp/openclaw-contract-wrong-token.out 2>&1; then
      rm -f /tmp/openclaw-contract-wrong-token.out
      echo "wrong Gateway token unexpectedly succeeded" >&2
      exit 1
    fi
    rm -f /tmp/openclaw-contract-wrong-token.out
    echo "wrong Gateway token check: OK"
  else
    echo "wrong-token check skipped because OPENCLAW_GATEWAY_TOKEN is not set"
  fi
else
  echo "Gateway RPC checks skipped: set OPENCLAW_GATEWAY_URL in an isolated environment to enable them."
fi
