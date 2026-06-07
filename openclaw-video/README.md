# OpenClaw Video Sidecar

Status: root-side OpenClaw sidecar is active for the current development and
acceptance phase. The current execution baseline is
`../openclaw-engineering-baseline.md`; older Phase 1/1.5 wording is historical
unless the user explicitly asks to re-enable those gates.

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

For the current OpenClaw page phase, the live gate is root-first OpenClaw
acceptance:

- OpenClaw-owned login on `/ai/openclaw-lab/` passes.
- Dify Web login is not required.
- Douyin account login, cookies and browser storage state are retired.
- video link-read mode is adopted.
- root public routes pass: Huahuo web 200, OpenClaw page 200, unauthenticated
  OpenClaw API 401.
- Dify `api`, `web` and `nginx` containers are not restarted or rebuilt.
- evidence is sanitized and committed.

Web GPT/ChatGPT review and local browser loops are not required for this phase
unless the user explicitly requests them.

## douyin_chong Candidate Intake

A local candidate Python package was found outside this repository at:

```text
D:\DESK\视频解析\tik\douyin_chong
```

It is not production verified. The sibling project contains `.env`,
`.env.local` and `.douyin_storage_state*` files; these must not be read, copied,
committed or deployed. A minimal V1 source subset is vendored at
`openclaw-video/vendor/douyin_chong`; runtime model credentials must be mounted
separately as `./secrets/douyin_chong.env`.

The worker calls the candidate through `openclaw-douyin-adapter`, not through
the candidate's default CLI. The current V1 scheme uses a user-provided video
link, validates/canonicalizes it through the URL guard, and resolves the direct
video URL candidates without a Douyin account login or browser storage state.
Production readiness no longer depends on committing
`artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json`.

Run a real model-backed sample only when an explicit video URL is provided and
the runtime secret file is already configured:

```bash
python scripts/run_douyin_real_sample.py \
  --input-url '<douyin-single-video-url>' \
  --env-file /path/to/douyin_chong.env \
  --adapter-bin openclaw-douyin-adapter
```

The runner writes sanitized evidence under `tmp/douyin-real-samples/` by
default. It records URL hash/host, timing, schema status and result hash/size;
it does not record the secret file, raw stdout/stderr, cookies, tokens or full
request headers.

## Unit Tests

The unit tests cover the pure safety logic and do not require server access.
For the current UI/root phase, do not use these local tests as the acceptance
gate unless the user explicitly asks for local testing:

```powershell
$env:PYTHONPATH='openclaw-video\src'
.\.phase1-sandbox\bridge-api-venv\Scripts\python.exe -m unittest discover openclaw-video\tests
```

Historical Phase 1.5 development gate on Windows without Docker:

```powershell
.\scripts\verify_phase1_5_gates.ps1 -PythonCmd .\.phase1-sandbox\bridge-api-venv\Scripts\python.exe -SkipDocker -AllowDirty
```

Historical Phase 1.5 exit gate on an isolated Linux Docker host:

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
PYTHON=/path/to/venv/bin/python scripts/verify_phase1_5_gates.sh
```

The historical isolated-host gate is retained for reference, but it no longer
blocks the current root-first OpenClaw UI/video-link phase.

## Current OpenClaw UI Verification Override

As of 2026-06-07, the active OpenClaw page work uses a root-first UI verification
policy. Finish UI implementation/debugging by code and design review first, then
deploy to the root sidecar and run browser/API acceptance there. Do not keep
reminding future agents to run a local browser or local test loop for this UI
phase unless the user explicitly asks for local testing.

This override applies to the OpenClaw-owned login, conversation, video
source selector, result panel and diagnostics UI. It does not authorize changes
to Dify `api`, `web` or `nginx` containers.

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

## Root Deployment Principle

Use the root server as the authoritative environment for this OpenClaw phase.
Deploy only reversible OpenClaw sidecar changes and preserve rollback markers.

Allowed:

- rebuild/recreate OpenClaw Bridge for the new release.
- keep Gateway, Worker and Bridge Postgres private.
- validate OpenClaw login, page UI, API gates and video-link analysis on root.

Not allowed without explicit approval:

- restarting, rebuilding or recreating Dify `api`, `web` or `nginx`.
- changing Dify compose for OpenClaw.
- exposing Gateway, Worker or Bridge Postgres as public browser targets.

After each root deployment, record sanitized evidence for:

- current release and previous release.
- Dify container ID/StartedAt invariants.
- public route checks.
- OpenClaw-owned login/post-login acceptance.
- desktop/mobile UI screenshots when UI changed.
- video link-read or full analysis evidence when a test URL is available.
