# Phase 2 Root Private Sidecar Deployment Evidence

Time: 2026-06-06 22:15 Asia/Shanghai

Scope: private OpenClaw sidecar deployment on the root server. This deployment
does not expose `/openclaw-lab/` or `/openclaw-api/` publicly and does not
modify or restart the existing Dify compose project.

## Version Control

Repository:

```text
git@github.com:Xieyangzai/dify_openclaw_viedo.git
```

Deployed commit:

```text
bdf81d3e28932c0bf6925e58854b6ec10e3016a2
```

Deployed tag:

```text
phase2-root-private-gateway-controlui-off-20260606
```

Remote verification:

```text
origin/master -> bdf81d3e28932c0bf6925e58854b6ec10e3016a2
origin tag phase2-root-private-gateway-controlui-off-20260606 -> bdf81d3e28932c0bf6925e58854b6ec10e3016a2
```

Bundle:

```text
local: D:\DESK\Dify\tmp\root-private-sidecar-bundles\openclaw-root-private-sidecar-bdf81d3e2893.tar.gz
root: /tmp/openclaw-root-private-sidecar-bdf81d3e2893.tar.gz
sha256: 4d6eb840126189121a28f3052a5a7716eadbb45ad4415dee98984ed2d5493df9
```

Root release:

```text
/app/bin/openclaw-video/releases/bdf81d3e2893
/app/bin/openclaw-video/current -> /app/bin/openclaw-video/releases/bdf81d3e2893
```

## Build Evidence

Build command:

```text
bash /app/bin/openclaw-video/current/scripts/root_private_sidecar_build.sh
```

Build log:

```text
/app/bin/openclaw-video/shared/logs/build-20260606220851.log
build_exit=0
```

Built images:

```text
openclaw-video-openclaw-gateway image id: daeedfa3ca40
openclaw-video-openclaw-bridge image id: 0250e212e98f
openclaw-video-video-analysis-worker image id: 28b5c948ee1b
```

## Runtime Evidence

Compose project:

```text
openclaw-video
```

Containers:

```text
openclaw-video-bridge-postgres-1         postgres:15-alpine                     running   Up (healthy)   5432/tcp
openclaw-video-openclaw-bridge-1         openclaw-video-openclaw-bridge         running   Up             127.0.0.1:18181->3000/tcp
openclaw-video-openclaw-gateway-1        openclaw-video-openclaw-gateway        running   Up             18789/tcp
openclaw-video-video-analysis-worker-1   openclaw-video-video-analysis-worker   running   Up
```

Host port exposure:

```text
127.0.0.1:18181 -> openclaw-bridge:3000
```

No host listener was observed for OpenClaw Gateway `18789` or Bridge Postgres
`5432`. Gateway and Postgres remain private to the sidecar Docker network.

Bridge local HTTP checks:

```text
http://127.0.0.1:18181/healthz -> 200
http://127.0.0.1:18181/openclaw-lab/ -> 200
http://127.0.0.1:18181/openclaw-api/me -> 401
```

Gateway checks:

```text
config path: /etc/openclaw/config.yaml
config valid: true
controlUi.enabled: false
bindMode: lan
bindHost: 0.0.0.0
port: 18789
RPC status: ok=true
health call: ok=true
defaultAgentId: main
session count: 0
```

Gateway status also reported a recommended-level `gateway-path-missing` audit
item because the service status tool cannot inspect a systemd-style daemon PATH
inside this containerized deployment. The container itself has the expected
PATH and the gateway RPC/health calls passed.

## Dify Baseline After Sidecar

No Dify compose file was changed. No Dify container was restarted or rebuilt.

Server-local Dify checks:

```text
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
```

Public Dify checks with the known production host:

```text
https://ai001.huahuoai.com/signin -> 200
https://ai001.huahuoai.com/apps -> 200
https://ai001.huahuoai.com/console/api/account/profile -> 401
```

The bare IP `http://8.148.28.240` is not the recorded production Dify baseline
host. Local and root-side HTTP probes to the bare IP failed, while the correct
production domain passed the unauthenticated baseline.

Dify container status:

```text
docker-nginx-1  nginx:latest                Up 5 months
docker-api-1    langgenius/dify-api:1.11.2  Up 5 months
docker-web-1    langgenius/dify-web:1.11.2  Up 5 months (unhealthy)
```

`docker-web-1` remains historically unhealthy because of the previously
recorded healthcheck issue. This deployment did not introduce or modify that
state.

## Current Gate Status

Passed:

```text
Git remote and tag present
Root release path created
Current symlink points to the deployed release
Sidecar build completed
Sidecar compose project running
Bridge local health passed
Private lab page served locally
Unauthenticated /openclaw-api/me rejects with 401
Gateway config valid
Gateway control UI disabled
Gateway RPC and health checks passed
Gateway/Postgres not exposed on host ports
Dify local unauthenticated baseline passed
Dify public unauthenticated baseline passed on https://ai001.huahuoai.com
```

Still gated before any public `/openclaw-lab/` route:

```text
Authenticated real-browser Dify baseline
Existing Dify app message send/reply/refresh/history/logout regression
Logged-in Bridge identity flow against Dify profile/workspaces
Double-user and tenant isolation tests
Real video job end-to-end test with production-like sample
OpenResty route include and rollback drill
```

## Rollback

Stop the sidecar only:

```bash
cd /app/bin/openclaw-video/current/openclaw-video
docker compose --env-file /app/bin/openclaw-video/shared/openclaw-video.env -p openclaw-video -f docker-compose.openclaw-video.yaml down
```

Switch to a previous release:

```bash
ln -sfn /app/bin/openclaw-video/releases/<previous_commit12> /app/bin/openclaw-video/current
```

Recreate sidecar from the selected release:

```bash
cd /app/bin/openclaw-video/current/openclaw-video
docker compose --env-file /app/bin/openclaw-video/shared/openclaw-video.env -p openclaw-video -f docker-compose.openclaw-video.yaml up -d --force-recreate
```

This rollback does not require restarting Dify, rebuilding Dify, or editing the
Dify compose project.

Post-rollback Dify checks:

```text
https://ai001.huahuoai.com/signin
https://ai001.huahuoai.com/apps
https://ai001.huahuoai.com/console/api/account/profile
```

Expected unauthenticated results:

```text
/signin -> 200
/apps -> 200 or current Dify login policy redirect
/console/api/account/profile -> 401
```
