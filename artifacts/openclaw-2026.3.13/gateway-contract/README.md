# OpenClaw Gateway Contract

Status: draft. The real Gateway API contract is not locked.

## Contract Principle

OpenClaw `2026.3.13` exposes a WebSocket Gateway and CLI RPC helpers such as
`openclaw gateway call <method>`. The Bridge must not assume an HTTP REST API
exists until it has been proven against the fixed artifact.

The local Bridge client currently contains an HTTP placeholder. That placeholder
is intentionally not approved for deployment.

## Required CLI Contract Evidence

The fixed artifact must pass these read-only checks:

```text
openclaw --version
openclaw --help
openclaw gateway --help
openclaw gateway call --help
openclaw gateway status --help
openclaw gateway probe --help
openclaw gateway run --help
openclaw doctor --help
openclaw health --help
openclaw status --help
openclaw agent --help
```

Expected version:

```text
OpenClaw 2026.3.13 (61d171a)
```

Important fixed-version facts observed locally:

- `gateway call <method>` supports methods described as
  `health/status/system-presence/cron.*`.
- `gateway status` supports `--json`, `--require-rpc`, `--url`, `--token` and
  `--timeout`.
- `gateway probe` supports `--json`, `--url`, `--token` and `--timeout`.
- `doctor` supports `--non-interactive`, `--generate-gateway-token` and
  repair flags, but does not expose `--lint` or `--json`.
- `gateway run` can start a foreground Gateway and includes risky operational
  flags such as `--force`; those flags are forbidden in read-only checks.

## Required Runtime Contract Tests

The Bridge must prove the exact fixed-version Gateway behavior before server
deployment:

- WebSocket URL and bind address.
- Gateway auth mode and token transport.
- `gateway call health` response schema.
- `gateway call status` response schema.
- exact agent/chat/response method or CLI/RPC adapter used by Bridge.
- timeout behavior.
- error response schema.
- wrong token behavior.
- missing token behavior.
- token rotation behavior.
- request payload schema.
- response payload schema.
- streaming/SSE support if used.
- no Gateway token leaks to browser API responses.

Minimum isolated-environment commands:

```bash
OPENCLAW_BIN=/path/to/openclaw \
EXPECTED_OPENCLAW_VERSION='OpenClaw 2026.3.13 (61d171a)' \
scripts/verify_openclaw_contract.sh

OPENCLAW_BIN=/path/to/openclaw \
OPENCLAW_GATEWAY_URL='ws://127.0.0.1:<port>' \
OPENCLAW_GATEWAY_TOKEN='<redacted-token>' \
scripts/verify_openclaw_contract.sh
```

On the current Windows workstation, use the PowerShell equivalent:

```powershell
$env:OPENCLAW_BIN = 'D:\DESK\Dify\.phase1-sandbox\openclaw-3.13\node_modules\.bin\openclaw.cmd'
.\scripts\verify_openclaw_contract.ps1
```

The script must never print `OPENCLAW_GATEWAY_TOKEN`.

## Forbidden During Read-Only Checks

Do not run:

```text
openclaw gateway install
openclaw gateway start
openclaw gateway restart
openclaw gateway stop
openclaw gateway run --force
openclaw gateway run --reset
openclaw doctor --repair
openclaw doctor --fix
openclaw reset
```

## Current HTTP Placeholder

The local draft client uses:

```text
GET  /health
POST /channels/dify-web/chat
Authorization: Bearer <gateway-token>
```

This path is intentionally treated as unproven. It must be replaced by a
verified Gateway adapter or explicitly approved by contract tests against the
fixed OpenClaw `2026.3.13` artifact. Until then, `/openclaw-api/chat` may return
`501` for non-video messages and video messages may only create async video
jobs.
