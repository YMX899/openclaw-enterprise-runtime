# OpenClaw Video Sidecar

Status: Phase 1 offline artifact draft. Do not deploy to production until all
gates in `../phase1-artifact-gates.md` pass.

This directory defines the sidecar architecture for an independent
`/openclaw-lab/` page and `/openclaw-api/` API in front of OpenClaw `2026.3.13`.
It is intentionally separate from Dify Web and Dify compose.

## Components

- `openclaw-bridge`: browser-facing static page and API.
- `bridge-postgres`: product database for users, sessions, jobs and results.
- `openclaw-gateway`: private OpenClaw Gateway running OpenClaw `2026.3.13`.
- `video-analysis-worker`: asynchronous worker calling a fixed `douyin_chong`
  wrapper.

Only `openclaw-bridge` is allowed to join Dify's `docker_default` network, and
only to call Dify API identity endpoints. Gateway, worker and Postgres stay on a
private sidecar network and expose no public host ports.

## Current Gate

The source here is not production-ready until these external artifacts are
supplied and verified:

- actual `douyin_chong` binary/source/image.
- OpenClaw Gateway API contract in a Docker/Linux isolated host with real model
  credentials.
- explicit security decision for npm audit findings affecting
  `openclaw@2026.3.13`.
- real Postgres container integration test for the durable queue migration and
  adapter.
- real Dify authenticated browser baseline.
- final ChatGPT web review captured in git.

## Local Unit Tests

The unit tests cover the pure safety logic and do not require server access:

```powershell
$env:PYTHONPATH='openclaw-video\src'
python -m unittest discover openclaw-video\tests
```

## OpenClaw Gateway Contract

Bridge V1 uses OpenClaw `2026.3.13` Gateway WebSocket v3, not the rejected
HTTP placeholder `/channels/dify-web/chat`.

Required Bridge inputs:

```text
OPENCLAW_GATEWAY_URL=ws://openclaw-gateway:18789
OPENCLAW_GATEWAY_TOKEN_FILE=/run/secrets/openclaw_gateway_token
OPENCLAW_GATEWAY_DEVICE_KEY_FILE=/run/secrets/openclaw_bridge_device_key.pem
```

The Bridge connects as `gateway-client` / `backend`, signs the v3 device auth
payload with an Ed25519 private key, and requests only `operator.read` plus
`operator.write`. Without the token file or device key file, non-video chat
stays disabled and returns `501`.

Run the fixed-version Gateway WS contract in an isolated environment:

```bash
OPENCLAW_GATEWAY_URL='ws://127.0.0.1:<port>' \
OPENCLAW_GATEWAY_TOKEN='<redacted-token>' \
node scripts/verify_openclaw_gateway_ws_contract.mjs
```

## Production Principle

No OpenClaw service may be deployed until this repository is clean, artifacts are
committed, generated image digests are recorded, and rollback has been tested in
a non-production or no-op mode.
