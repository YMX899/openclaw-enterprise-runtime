# Phase 3 OpenClaw Lab Independent Public Port Evidence

Time: 2026-06-06 22:49 Asia/Shanghai

Scope: expose OpenClaw Lab on an independent public TLS port without changing
the existing Dify `80/443` routes and without modifying Dify compose.

## Version

Repository:

```text
git@github.com:Xieyangzai/dify_openclaw_viedo.git
```

Commit deployed to root:

```text
437c0627ab993e3f6b9a95df240d820266044736
```

Tag:

```text
phase3-public-port-firewall-managed-20260606
```

Root release:

```text
/app/bin/openclaw-video/releases/437c0627ab99
/app/bin/openclaw-video/current -> /app/bin/openclaw-video/releases/437c0627ab99
```

Bundle:

```text
local: D:\DESK\Dify\tmp\root-private-sidecar-bundles\openclaw-root-private-sidecar-437c0627ab99.tar.gz
root: /tmp/openclaw-root-private-sidecar-437c0627ab99.tar.gz
sha256: 088ebb265487900b0a3b00dbba8855e7cd479db0c202c6cfb999e1f34180e87e
```

## Installed Route

Public URL:

```text
https://ai001.huahuoai.com:18443/openclaw-lab/
https://ai001.huahuoai.com:18443/openclaw-api/
```

OpenResty managed config:

```text
/app/config/openresty/conf/conf.d/openclaw-lab-public-18443.conf
sha256: 3c4a9d9025f2a0e42ea5b2c76aab13a60be9e547f3293cd0865a16a5871ae429
```

Route summary:

```text
listen 18443 ssl
server_name ai001.huahuoai.com
/openclaw-lab/ -> http://127.0.0.1:18181
/openclaw-api/ -> http://127.0.0.1:18181
/ -> 302 /openclaw-lab/
other paths -> 404
```

UFW rules:

```text
18443/tcp      ALLOW IN    Anywhere       # openclaw-lab-public-port-18443
18443/tcp (v6) ALLOW IN    Anywhere (v6)  # openclaw-lab-public-port-18443
```

The UFW rule was required because root UFW default incoming policy is deny and
only `80/tcp`, `443/tcp`, `22/tcp`, and a few internal/source-scoped rules were
previously allowed.

## Install Command

```bash
OPENCLAW_PUBLIC_PORT=18443 bash /app/bin/openclaw-video/current/scripts/install_openclaw_lab_public_port.sh
```

Observed result:

```text
public_port_install=PASS
local_https_lab=200
local_https_me=401
openresty -t: successful
openresty -s reload: completed
```

## Public Tests

From the local workstation:

```text
https://ai001.huahuoai.com:18443/openclaw-lab/ -> 200, 6278 bytes
https://ai001.huahuoai.com:18443/openclaw-api/me -> 401, 27 bytes
```

The same endpoint also responded through the resolved public IP:

```text
https://123.57.81.44:18443/openclaw-lab/ -> 200
https://123.57.81.44:18443/openclaw-api/me -> 401
```

No Cookie, Authorization, CSRF token, browser storage, or full request headers
were recorded.

## Dify Baseline After Public Port

Public Dify baseline:

```text
https://ai001.huahuoai.com/signin -> 200
https://ai001.huahuoai.com/apps -> 200
https://ai001.huahuoai.com/console/api/account/profile -> 401
```

Server-local Dify baseline:

```text
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
```

Dify containers:

```text
docker-nginx-1 | nginx:latest               | Up 5 months
docker-api-1   | langgenius/dify-api:1.11.2 | Up 5 months
docker-web-1   | langgenius/dify-web:1.11.2 | Up 5 months (unhealthy)
```

The `docker-web-1` unhealthy status is the previously recorded healthcheck
baseline and was not introduced by this change.

## Sidecar Status

```text
openclaw-video-bridge-postgres-1       running | healthy | 5432/tcp internal only
openclaw-video-openclaw-bridge-1       running | 127.0.0.1:18181->3000/tcp
openclaw-video-openclaw-gateway-1      running | 18789/tcp internal only
openclaw-video-video-analysis-worker-1 running
```

Host listeners relevant to this change:

```text
0.0.0.0:18443 -> OpenResty
127.0.0.1:18181 -> OpenClaw Bridge
```

No host listeners were observed for OpenClaw Gateway `18789` or Bridge Postgres
`5432`.

## What Changed

Changed:

```text
Added /app/config/openresty/conf/conf.d/openclaw-lab-public-18443.conf
Reloaded openresty-prod
Allowed 18443/tcp in UFW with a managed OpenClaw comment
```

Not changed:

```text
Dify compose
Dify docker-api-1
Dify docker-web-1
Dify docker-nginx-1
Dify 80/443 route definitions
OpenClaw Gateway public exposure
Bridge Postgres public exposure
```

## Rollback

Rollback public route and firewall rule:

```bash
OPENCLAW_PUBLIC_PORT=18443 bash /app/bin/openclaw-video/current/scripts/rollback_openclaw_lab_public_port.sh
```

Rollback sidecar only, if needed:

```bash
cd /app/bin/openclaw-video/current/openclaw-video
docker compose --env-file /app/bin/openclaw-video/shared/openclaw-video.env -p openclaw-video -f docker-compose.openclaw-video.yaml down
```

Rollback release pointer:

```bash
ln -sfn /app/bin/openclaw-video/releases/<previous_commit12> /app/bin/openclaw-video/current
```

Post-rollback required checks:

```text
https://ai001.huahuoai.com/signin -> 200
https://ai001.huahuoai.com/apps -> 200 or current Dify login-policy redirect
https://ai001.huahuoai.com/console/api/account/profile -> 401 when not logged in
https://ai001.huahuoai.com:18443/openclaw-lab/ -> unreachable after public-route rollback
```

## Remaining Gates

Still required before broad/production user rollout:

```text
Authenticated real-browser Dify app regression
Bridge logged-in /openclaw-api/me identity proof using Dify profile/workspaces
two-user and tenant isolation test
real video job end-to-end test
browser Network verification that Gateway token is never exposed
```
