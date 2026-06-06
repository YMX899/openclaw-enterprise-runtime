# Phase 4 Current Root Sidecar Verification - 2026-06-07

## Scope

This document records the current production-side verification for the OpenClaw sidecar after deploying commit `84d0feff0862aec249f25ea6842db50394cf6c17` tagged `phase4-retention-cleanup-20260607`.

The verification intentionally does not record cookies, authorization headers, CSRF tokens, database URLs, Redis secrets, OpenClaw tokens, API keys, TLS private keys, or full environment dumps.

## Version And Rollback

- Current release symlink: `/app/bin/openclaw-video/current -> /app/bin/openclaw-video/releases/84d0feff0862`
- Previous release marker: `/app/bin/openclaw-video/previous-current-before-84d0feff0862.txt`
- Previous release target: `/app/bin/openclaw-video/releases/774222263f91`
- Git commit: `84d0feff0862aec249f25ea6842db50394cf6c17`
- Git tag: `phase4-retention-cleanup-20260607`

Rollback target remains independent of Dify. Rolling back this sidecar version should only require switching the OpenClaw `current` symlink back to the previous release and recreating OpenClaw sidecar services; the Dify compose project must not be modified.

## OpenClaw Sidecar Status

Remote command via SSH skill:

```text
docker compose --env-file /app/bin/openclaw-video/shared/openclaw-video.env \
  -p openclaw-video \
  -f /app/bin/openclaw-video/current/openclaw-video/docker-compose.openclaw-video.yaml ps
```

Observed services:

```text
openclaw-video-bridge-postgres-1         postgres:15-alpine                    Up 4 hours (healthy)   5432/tcp
openclaw-video-openclaw-bridge-1         openclaw-video-openclaw-bridge:fast   Up 6 minutes           127.0.0.1:18181->3000/tcp
openclaw-video-openclaw-gateway-1        openclaw-video-openclaw-gateway       Up 4 hours             18789/tcp
openclaw-video-video-analysis-worker-1   openclaw-video-video-analysis-worker  Up About an hour
```

HTTP checks from the root host:

```text
GET  http://127.0.0.1:18181/healthz                         -> 200
GET  http://127.0.0.1:18181/openclaw-api/me                  -> 401
POST http://127.0.0.1:18181/openclaw-api/retention/cleanup   -> 401
```

The unauthenticated 401 responses are expected.

## Dify Baseline

HTTP checks from the root host:

```text
GET http://127.0.0.1:8081/signin                       -> 200
GET http://127.0.0.1:8081/apps                         -> 200
GET http://127.0.0.1:8081/console/api/account/profile  -> 401
```

Relevant Dify containers are still long-running:

```text
docker-nginx-1  nginx:latest                Up 5 months
docker-api-1    langgenius/dify-api:1.11.2  Up 5 months
docker-web-1    langgenius/dify-web:1.11.2  Up 5 months (unhealthy)
```

The `docker-web-1` unhealthy state is a pre-existing baseline caused by its healthcheck and is not introduced by the OpenClaw sidecar.

## Network And Port Exposure

OpenClaw network shape:

- `openclaw-video-openclaw-bridge-1` joins both `docker_default` and `openclaw_video_internal`.
- `openclaw-video-openclaw-gateway-1` joins only `openclaw_video_internal`.
- `openclaw-video-video-analysis-worker-1` joins only `openclaw_video_internal`.
- `openclaw-video-bridge-postgres-1` joins only `openclaw_video_internal`.

Host listeners observed:

```text
127.0.0.1:18181 -> openclaw-video-openclaw-bridge-1
0.0.0.0:18443   -> openresty public OpenClaw test port
0.0.0.0:80/443  -> openresty production entry
0.0.0.0:8081/8443 -> existing Dify nginx mappings
```

No OpenClaw Gateway or Bridge Postgres host-published public listener was observed. Gateway `18789/tcp` and Postgres `5432/tcp` appear only as container/internal ports.

## Public Smoke

Command:

```text
.\.phase1-sandbox\bridge-api-venv\Scripts\python.exe scripts\run_public_browser_smoke.py \
  --output-dir tmp\playwright-public-browser-current \
  --timeout-seconds 30
```

Result:

```text
status=PASS
run_dir=tmp\playwright-public-browser-current\20260606T174330Z
```

Public checks:

```text
GET https://ai001.huahuoai.com:18443/openclaw-lab/       -> 200
GET https://ai001.huahuoai.com:18443/openclaw-api/me     -> 401
GET https://ai001.huahuoai.com/signin                    -> 200
GET https://ai001.huahuoai.com/console/api/account/profile -> 401
```

Smoke summary:

- HTTP 5xx count: `0`
- Gateway direct request count: `0`
- Token URL leak count: `0`
- Headers recorded in summary: `false`
- Bodies recorded in summary: `false`
- Secrets recorded: `false`

## Remaining Gap

The Chrome automation channel needed for logged-in browser validation and web GPT review is still unavailable in the current Codex runtime. The failure happens before page/browser interaction while the local browser-control runtime writes its kernel assets:

```text
failed to write kernel assets: 系统找不到指定的路径。 (os error 3)
```

Because the Chrome skill explicitly requires the Chrome-backed Node runtime and forbids replacing it with an unrelated browser automation path for the user-login surface, the following remain pending:

- Web GPT review through the already logged-in Chrome page `https://www.huahuoai.com/ai?id=4`.
- Real logged-in Dify browser regression for `/apps`, existing app opening, message send, streaming/normal reply, refresh, history, and logout.
- Real logged-in OpenClaw Lab browser validation through the public port with Dify login cookies.

