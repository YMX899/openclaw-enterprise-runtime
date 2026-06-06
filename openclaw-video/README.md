# OpenClaw Video Sidecar

Status: Phase 1 offline artifact draft. Do not deploy to production until all
gates in `../phase1-artifact-gates.md` and
`../phase1.5-isolated-docker-gates.md` pass.

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
- Phase 1.5 isolated Linux Docker validation.

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
the candidate's default CLI. Production remains blocked until pinned
dependencies, real model-backed sample runs, schema validation, resource
profile and isolated Docker validation are complete.

Run a real model-backed sample only in an isolated environment with an explicit
runtime secret file:

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

## Local Unit Tests

The unit tests cover the pure safety logic and do not require server access:

```powershell
$env:PYTHONPATH='openclaw-video\src'
.\.phase1-sandbox\bridge-api-venv\Scripts\python.exe -m unittest discover openclaw-video\tests
```

Phase 1.5 development gate on Windows without Docker:

```powershell
.\scripts\verify_phase1_5_gates.ps1 -PythonCmd .\.phase1-sandbox\bridge-api-venv\Scripts\python.exe -SkipDocker -AllowDirty
```

Phase 1.5 exit gate on an isolated Linux Docker host:

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
PYTHON=/path/to/venv/bin/python scripts/verify_phase1_5_gates.sh
```

The exit gate must run from a clean git worktree and must not be run for the
first time on the production Dify server.

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

The production Dify server must not be the first environment used to test
Docker build, compose render, sidecar startup, Gateway WS v3 runtime behavior,
or worker resource limits.

Before any future root-server deployment attempt, the local evidence gate must
return `GO`:

```bash
python scripts/preflight_root_deploy.py --target-host root --fail-on-no-go
```

This preflight intentionally fails closed until the ubuntu22.04 or another
non-production Linux Docker host has produced a valid `phase1.5-exit-proof.md`
and the production readiness audit is fully `GO`.

After the preflight returns `GO`, build the sanitized root deployment bundle
instead of uploading a working directory by hand:

```bash
python scripts/build_root_deploy_bundle.py --target-host root --fail-on-no-go
```

The bundle builder records the git commit, tags, SHA256 digest and preflight
report, and refuses to create a bundle while the preflight is `NO_GO`.

## Root Private Sidecar Deployment

When the production public browser baseline is still blocked, the only allowed
root deployment scope is a private Phase 2 sidecar:

- no OpenResty route.
- no Dify compose change.
- no Dify container restart.
- `openclaw-bridge` bound only to `127.0.0.1:18181`.
- OpenClaw Gateway, worker and Postgres without host-published ports.
- `bridge-postgres` uses `postgres:15-alpine` for the private root sidecar,
  matching the image already present on the production host. The schema only
  uses PostgreSQL 15-compatible features.

Use the narrower private preflight and bundle builder for that scope:

```bash
python scripts/preflight_root_private_sidecar.py --target-host root --fail-on-no-go
python scripts/build_root_private_sidecar_bundle.py --target-host root --fail-on-no-go
```

This private gate does not authorize `/openclaw-lab/` or `/openclaw-api/`
public routes. Public routing still requires the full
`scripts/preflight_root_deploy.py` gate to return `GO`.
