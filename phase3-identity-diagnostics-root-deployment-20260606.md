# Phase 3 Identity Diagnostics Root Deployment

Time: 2026-06-06 23:24 Asia/Shanghai

Scope: deploy a safe Dify identity diagnostics endpoint to the already-public
independent OpenClaw Lab port.

## Updated Development Policy

The gate has been relaxed for most OpenClaw sidecar work. Development and
verification may now happen directly on the root server when scoped to the
`openclaw-video` sidecar.

Allowed direct root development:

```text
rebuild/recreate openclaw-video-openclaw-bridge-1
rebuild/recreate openclaw-video-video-analysis-worker-1
rebuild/recreate openclaw-video-openclaw-gateway-1
run OpenClaw sidecar tests and probes
update the independent OpenClaw public port route
reload openresty-prod for the independent OpenClaw port
manage the tagged UFW rule for 18443/tcp
```

Still protected:

```text
do not modify Dify compose for sidecar development
do not rebuild docker-api-1
do not rebuild docker-web-1
do not rebuild docker-nginx-1
do not direct-edit files inside running Dify containers
do not read or record cookies, tokens, CSRF values, .env files, DB passwords or TLS private keys
```

## Git Version

Repository:

```text
git@github.com:Xieyangzai/dify_openclaw_viedo.git
```

Deployed root release:

```text
commit: 01ddff9bd500fd2fa2000754bf8c8dcf28416d13
tag: phase3-root-fast-bridge-rebuild-20260606
root current: /app/bin/openclaw-video/releases/01ddff9bd500
```

Identity diagnostics commit:

```text
fe6486fae37f07352a4a568f108ca1969a065175
tag: phase3-identity-diagnostics-20260606
```

Bundle:

```text
local: D:\DESK\Dify\tmp\root-private-sidecar-bundles\openclaw-root-private-sidecar-01ddff9bd500.tar.gz
root: /tmp/openclaw-root-private-sidecar-01ddff9bd500.tar.gz
sha256: 5eb39af074f9fe01e54af727eded74521ecc06d38ca6e7138cbad4fdb632daf8
```

## New Endpoint

```text
GET /openclaw-api/identity/diagnostics
```

Purpose:

```text
verify whether the browser supplied Dify login material
verify whether Dify profile lookup succeeds
verify whether Dify workspaces lookup resolves exactly one current workspace
return only hashed principal_id when authenticated
```

The endpoint must not return:

```text
Cookie
Authorization
CSRF token
raw account_id
raw tenant_id
workspace list
Gateway token
```

Unauthenticated public response:

```json
{
  "authenticated": false,
  "login_material_present": false,
  "profile_ok": false,
  "workspace_ok": false,
  "current_workspace_count": 0,
  "principal_id": null,
  "failure_stage": "profile"
}
```

## Fast Root Bridge Rebuild

Script added:

```text
/app/bin/openclaw-video/current/scripts/root_rebuild_bridge_fast.sh
```

It reuses the existing Bridge image and installs only changed source:

```text
pip install --no-cache-dir --no-deps /app
docker compose ... up -d --no-deps --force-recreate openclaw-bridge
```

Observed root result:

```text
bridge_fast_rebuild=PASS
openclaw-video-openclaw-bridge-1 -> openclaw-video-openclaw-bridge:fast
```

This was added because a full `docker compose up --build` attempted to rebuild
unrelated sidecar services and stalled on remote apt/pip network steps. The
stalled OpenClaw build processes were terminated; Dify containers were not
touched.

## Verification

Local tests:

```text
Ran 187 tests
OK
```

Public OpenClaw checks:

```text
https://ai001.huahuoai.com:18443/openclaw-lab/ -> 200
https://ai001.huahuoai.com:18443/openclaw-api/identity/diagnostics -> 200
https://ai001.huahuoai.com:18443/openclaw-api/me -> 401
```

Public diagnostics response:

```text
authenticated=false
login_material_present=false
profile_ok=false
workspace_ok=false
principal_id=null
failure_stage=profile
```

Server-local diagnostics checks:

```text
http://127.0.0.1:18181/openclaw-api/identity/diagnostics -> 200
https://ai001.huahuoai.com:18443/openclaw-api/identity/diagnostics via 127.0.0.1 resolve -> 200
https://ai001.huahuoai.com:18443/openclaw-api/me via 127.0.0.1 resolve -> 401
```

Dify public baseline after deployment:

```text
https://ai001.huahuoai.com/signin -> 200
https://ai001.huahuoai.com/apps -> 200
https://ai001.huahuoai.com/console/api/account/profile -> 401
```

Dify server-local baseline:

```text
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
```

Bridge runtime proof:

```text
openclaw_video.bridge_app has _has_dify_login_material: True
```

## Remaining Gates

Still required:

```text
real logged-in browser check for /openclaw-api/identity/diagnostics
Bridge logged-in /openclaw-api/me proof with Dify profile/workspaces
session creation with real Dify login
two-user isolation with real or simulated separate accounts
real video job end-to-end test
browser Network verification that Gateway token is never exposed
```
