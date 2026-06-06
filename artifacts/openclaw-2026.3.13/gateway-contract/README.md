# OpenClaw Gateway Contract

Status: partially locked by local isolated tests. This is still not production
approval because Docker build, model credentials, `douyin_chong`, security
triage, and server acceptance tests remain incomplete.

## Contract Principle

OpenClaw `2026.3.13` exposes a WebSocket Gateway and CLI RPC helpers such as
`openclaw gateway call <method>`. The Bridge must not assume an HTTP REST API
exists until it has been proven against the fixed artifact.

The previous local Bridge HTTP placeholder has been removed. Bridge V1 must use
the WebSocket v3 Gateway data plane for non-video chat.

## Locked V1 Bridge Contract

Observed against local OpenClaw `2026.3.13 (61d171a)` Gateway on
`2026-06-06`:

- Transport is WebSocket JSON frames.
- First client request is `connect` with `minProtocol=3` and `maxProtocol=3`.
- Allowed backend client identity is `client.id="gateway-client"` and
  `client.mode="backend"`.
- Arbitrary custom client ids are rejected during connect validation.
- Shared token alone can authenticate the socket, but without signed device
  identity OpenClaw clears requested scopes; subsequent `status`,
  `chat.history` and `chat.send` fail with `missing scope`.
- Signed Ed25519 device identity plus shared token preserves scopes.
- Minimum Bridge scopes for chat are `operator.read` and `operator.write`.
  `operator.admin` is not required and must not be granted to Bridge V1.
- `chat.history` accepts `{sessionKey, limit}` and returns current transcript
  data.
- `chat.send` accepts `{sessionKey, message, idempotencyKey, deliver,
  timeoutMs}` and returns an immediate ack like `{runId, status:"started"}`.
- Terminal chat output arrives asynchronously as a Gateway `chat` event with
  `state` in `final/error/aborted`.
- Wrong shared token fails closed with `AUTH_TOKEN_MISMATCH`.

Bridge session mapping:

```text
openclaw_session_key = "agent:main:" + openclaw_routing_user
```

`openclaw_routing_user` is already an HMAC value derived from Dify tenant,
account and Bridge session. The Bridge must not send raw Dify tenant/account IDs
to OpenClaw.

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
- exact `chat.history` / `chat.send` WebSocket methods used by Bridge.
- Ed25519 device signing behavior and scope preservation.
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

Additional WebSocket data-plane contract:

```bash
OPENCLAW_GATEWAY_URL='ws://127.0.0.1:<port>' \
OPENCLAW_GATEWAY_TOKEN='<redacted-token>' \
node scripts/verify_openclaw_gateway_ws_contract.mjs

# Optional: also trigger chat.send and wait for a terminal chat event.
OPENCLAW_GATEWAY_WS_CHAT_SEND=1 \
OPENCLAW_GATEWAY_URL='ws://127.0.0.1:<port>' \
OPENCLAW_GATEWAY_TOKEN='<redacted-token>' \
node scripts/verify_openclaw_gateway_ws_contract.mjs --chat-send
```

The script generates an ephemeral Ed25519 device identity and must not print the
Gateway token, private key, public key, device id, signature or instance id.

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

## Rejected HTTP Placeholder

The earlier local draft client used:

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

Current decision:

```text
POST /channels/dify-web/chat is rejected for V1.
Bridge V1 uses WebSocket v3 chat.history/chat.send only.
```

## Runtime Secret Handling

Required Bridge inputs:

```text
OPENCLAW_GATEWAY_URL=ws://openclaw-gateway:18789
OPENCLAW_GATEWAY_TOKEN_FILE=/run/secrets/openclaw_gateway_token
OPENCLAW_GATEWAY_DEVICE_KEY_FILE=/run/secrets/openclaw_bridge_device_key.pem
```

The Bridge fails closed and returns `501` for non-video chat if any of these are
missing. The Gateway token and Bridge device private key are mounted read-only
and are never returned to browser-facing API responses.

OpenClaw `gateway run` in `2026.3.13` supports `--password-file` but not
`--token-file`. The Gateway container therefore reads the token from a read-only
file and exports `OPENCLAW_GATEWAY_TOKEN` inside the entrypoint before `exec`.
The token must not be passed as `--token <value>` because command-line
arguments can leak through process listings.

## Current Runtime Gaps

- Local `chat.send` ack/event shape was verified, but the sandbox has no model
  provider API key; final output was an OpenClaw agent failure event. The Bridge
  now treats that internal failure text as a Gateway error instead of a normal
  assistant reply.
- Production still needs model credential provisioning for the OpenClaw agent.
- Production still needs OpenClaw security audit triage before server deploy.
