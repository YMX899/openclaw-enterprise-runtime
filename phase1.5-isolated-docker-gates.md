# Phase 1.5 Isolated Docker Gates

Date: 2026-06-06 Asia/Shanghai

Status: required before any production server sidecar deployment.

## Source Of This Gate

This gate was added after a fresh ChatGPT web review in GPT-5.5 Thinking mode
on 2026-06-06. The review used the current repository state after commit
`ae72206` / tag `phase1-openclaw-gateway-ws-v3`.

The review verdict was:

```text
Production server Phase 2 sidecar deployment: NO-GO
Allowed next step: Phase 1.5 isolated Docker/Linux validation
```

The execution preflight review after commit `c4fd167` / tag
`phase1-5-executable-gates` confirmed this file and the executable gate scripts
are suitable as the isolated validation entry point. It also confirmed that
they are not production deployment approval while the real video tool, isolated
Docker run, Dify baseline and OpenClaw security decision remain incomplete.

## Why Production Phase 2 Is Still No-Go

The Bridge and OpenClaw Gateway WebSocket v3 direction is acceptable, but the
project still lacks the evidence needed to claim a 100% deployable system that
does not affect Dify:

- a local `douyin_chong` candidate has been located and a minimal V1 source
  subset has been vendored, but it is not yet model-verified and must not be
  treated as production-ready.
- the real video tool has not proven input/output schema, error codes,
  duration, resource use, temp cleanup, or failure behavior.
- Docker build, compose render, entrypoints, networks, volumes, health checks
  and port bindings have not been verified on an isolated Linux Docker host.
- authenticated real public Dify baseline is incomplete.
- OpenClaw `2026.3.13` security decision is unresolved.
- OpenClaw Gateway WS v3 contract has been proven locally, but not yet inside
  the deployment compose with production model credentials.

## Required Phase 1.5 Work

### P0: Real Video Tool Contract

The project must supply the actual video-analysis artifact before production
server deployment:

- binary, source, or image location.
- fixed invocation command.
- accepted input parameters.
- output JSON Schema and schema version.
- stable error codes.
- expected average and worst-case runtime.
- CPU, memory, disk and temp directory behavior.
- timeout and cleanup behavior.
- at least one successful sample and negative samples for SSRF, timeout and
  oversize rejection.
- proof that the vendored minimal source excludes `.env`, `.env.local`,
  `.douyin_storage_state*`, generated outputs, logs, caches and cookies.

The worker may call the video tool only through a fixed wrapper. User input must
not be interpolated into shell commands.

The current adapter entry point for the located candidate is:

```text
openclaw-douyin-adapter
```

It is still blocked until the vendored minimal source is tested with a runtime
secret file in an isolated Linux Docker host and proves the real model-backed
V1 single-video path.

### P0: Isolated Docker/Linux Validation

Run in a non-production Linux Docker host, not on the Dify server:

```bash
git status --short
git rev-parse HEAD
git tag --points-at HEAD

python -c 'import cryptography, fastapi, httpx, jsonschema, psycopg, pydantic, websockets; from psycopg.types.json import Jsonb'
python -m unittest discover openclaw-video/tests -v
python -m compileall openclaw-video/src openclaw-video/tests
node --check scripts/verify_openclaw_gateway_ws_contract.mjs

docker compose -f openclaw-video/docker-compose.openclaw-video.yaml config
docker compose -f openclaw-video/docker-compose.openclaw-video.yaml build --no-cache
docker compose -f openclaw-video/docker-compose.openclaw-video.yaml up -d
docker compose -f openclaw-video/docker-compose.openclaw-video.yaml ps
```

The same gate is codified in:

```bash
scripts/verify_phase1_5_gates.sh
```

If the isolated host uses a virtual environment, pin the interpreter explicitly:

```bash
PYTHON=/path/to/venv/bin/python scripts/verify_phase1_5_gates.sh
```

On Windows workstations without Docker, a development-only static check can run:

```powershell
.\scripts\verify_phase1_5_gates.ps1 -PythonCmd .\.phase1-sandbox\bridge-api-venv\Scripts\python.exe -SkipDocker -AllowDirty
```

This static check is useful while editing, but it is not Phase 1.5 exit
evidence. Phase 1.5 exit requires a clean worktree and a non-production Linux
Docker host running the full script without `SKIP_DOCKER=1`.

The full Linux/Docker script must also prove:

- vendored `douyin_chong` files match `SOURCE_SHA256SUMS`.
- no `.env`, storage state, cache, `.pyc`, log or browser-state utility exists
  in the vendored V1 subset.
- the worker image builds from the compose file.
- `openclaw-douyin-adapter --help` works inside the built worker image.
- the adapter loader imports the vendored candidate package inside the built
  worker image.
- when `RUN_COMPOSE_UP=1`, the stack is torn down afterward with
  `docker compose down --remove-orphans`.

Verify host exposure:

```bash
ss -lntp | grep -E '18181|18789|5432|18190|18192' || true
curl -fsS http://127.0.0.1:18181/healthz
```

Required result:

- Bridge binds only `127.0.0.1:18181`.
- Gateway has no public host port.
- Worker has no public host port.
- Bridge Postgres has no public host port.
- only Bridge joins Dify `docker_default` when the test intentionally attaches
  to a Dify-compatible network.
- worker concurrency starts at `1`.
- token values do not appear in compose output, process command-line arguments,
  browser responses or application logs.
- `18190` and `18192` are not left listening after Gateway contract tests.

### P0: Dify Baseline Before Production Server Deployment

Before any server-side sidecar deployment, record a real Dify baseline. This is
read-only and must not restart, rebuild, or modify Dify:

- current server time.
- Dify container IDs, image IDs, status and restart counts.
- `docker-web-1` unhealthy state and known `pg_isready` healthcheck cause.
- public `/signin`.
- public `/apps`.
- authenticated Dify login.
- existing app open.
- existing app message send.
- streaming or normal reply.
- page refresh.
- history access.
- logout.
- unauthenticated profile returns `401`.

The existing `docker-web-1` unhealthy status may be registered as a historical
baseline anomaly. Fixing that healthcheck requires a separate Dify maintenance
window and must not be mixed with OpenClaw sidecar work.

## Gateway WS v3 Design Notes

No fatal design issue was found in the current WebSocket v3 direction, with
these production constraints:

- Bridge must use `client.id="gateway-client"` and `client.mode="backend"`.
- Bridge must sign the v3 device auth payload with an Ed25519 device key.
- Bridge must request only `operator.read` and `operator.write`.
- `operator.admin` is forbidden for V1.
- Bridge must use `sessionKey="agent:main:<openclaw_routing_user>"`.
- `openclaw_routing_user` must remain HMAC-derived and must not expose raw Dify
  tenant/account IDs.
- Gateway token and device key must be mounted read-only and never sent to the
  browser.
- Because OpenClaw `2026.3.13` has no `--token-file`, the Gateway container may
  read the token from a read-only file into process environment as a constrained
  workaround. This residual risk must be documented: Docker/root administrators
  are trusted operators and can inspect container state.
- OpenClaw internal agent failure text must be treated as a Gateway error, not
  normal assistant content.

## Low-Risk Order After Phase 1.5 Passes

Only after all P0 gates pass:

1. create a new clean git commit and tag for the Phase 1.5 exit.
2. run production server Dify baseline read-only.
3. create a versioned production deployment directory outside the Dify tree.
4. start sidecar control-plane services on localhost only, without public
   OpenResty routes.
5. verify Bridge health, private Gateway reachability and Dify unchanged state.
6. start worker only after control-plane checks pass.
7. run localhost-only safety jobs, including SSRF rejection.
8. add OpenResty `/openclaw-lab/` and `/openclaw-api/` only after sidecar-local
   acceptance passes.
9. keep rollback independent from Dify containers.

## Current Decision

```text
Phase 1.5 isolated Docker/Linux validation: GO
Production server Phase 2 sidecar deployment: NO-GO
OpenResty public route change: NO-GO
Dify Web / Dify compose modification: NO-GO
```
