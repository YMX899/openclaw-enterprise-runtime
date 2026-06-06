# OpenClaw Lab Independent Public Port Runbook

Status: Phase 3 candidate

This runbook exposes the already-running private Bridge on an independent
public TLS port. It intentionally does not add `/openclaw-lab/` to the existing
Dify `80/443` routes and does not modify Dify compose.

## Target Shape

```text
https://ai001.huahuoai.com:18443/openclaw-lab/
https://ai001.huahuoai.com:18443/openclaw-api/
  -> openresty-prod host network
  -> 127.0.0.1:18181
  -> openclaw-video-openclaw-bridge-1
```

Preserved Dify routes:

```text
https://ai001.huahuoai.com/
https://ai001.huahuoai.com/signin
https://ai001.huahuoai.com/apps
https://ai001.huahuoai.com/console/api/*
```

## Install

Run on the root server from a deployed repository release:

```bash
OPENCLAW_PUBLIC_PORT=18443 bash /app/bin/openclaw-video/current/scripts/install_openclaw_lab_public_port.sh
```

The script:

```text
checks that openresty-prod is running
checks that the Bridge is healthy on 127.0.0.1:18181
extracts TLS certificate directives from the existing ai001.huahuoai.com server
writes a dedicated conf.d/openclaw-lab-public-18443.conf file
runs openresty -t
reloads OpenResty only after syntax passes
checks /openclaw-lab/ returns 200 locally over HTTPS
checks unauthenticated /openclaw-api/me returns 401 locally over HTTPS
```

## Rollback

```bash
OPENCLAW_PUBLIC_PORT=18443 bash /app/bin/openclaw-video/current/scripts/rollback_openclaw_lab_public_port.sh
```

The rollback script:

```text
backs up the managed OpenClaw public-port config
removes only conf.d/openclaw-lab-public-18443.conf
runs openresty -t
reloads OpenResty
does not stop or restart Dify
does not change Dify compose
```

## Required Tests After Install

Public unauthenticated checks:

```text
https://ai001.huahuoai.com:18443/openclaw-lab/ -> 200
https://ai001.huahuoai.com:18443/openclaw-api/me -> 401
https://ai001.huahuoai.com/signin -> 200
https://ai001.huahuoai.com/apps -> 200
https://ai001.huahuoai.com/console/api/account/profile -> 401
```

Server checks:

```text
ss -ltnp shows 0.0.0.0:18443 under OpenResty
ss -ltnp does not show host listeners for 18789 or 5432
docker compose -p openclaw-video ps remains healthy/up
docker ps shows docker-api-1, docker-web-1, docker-nginx-1 unchanged
```

Browser checks:

```text
Open https://ai001.huahuoai.com:18443/openclaw-lab/
Confirm the page loads.
Confirm browser Network does not call OpenClaw Gateway directly.
Confirm browser Network does not expose a Gateway token.
```

Authenticated checks still required before broad use:

```text
Dify login-state identity bridge through /openclaw-api/me
existing Dify app message send/reply/refresh/history/logout regression
two-user session/job isolation
real video job end-to-end test
```

## Versioning

Every public-port install must record:

```text
git commit
git tag
config file path
config sha256
OpenResty syntax-check result
reload time
public status codes
Dify baseline status codes
rollback command
```
