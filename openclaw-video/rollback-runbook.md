# Rollback Runbook

This runbook applies only after a future approved sidecar deployment. It does
not authorize changing Dify containers or Dify compose.

## Rollback Goals

- Remove `/openclaw-lab/` and `/openclaw-api/` public routes.
- Stop the `openclaw-video` compose project.
- Keep Dify containers running.
- Keep Dify data untouched.
- Restore OpenResty config from the pre-change backup if a route file was added.

## Pre-change Evidence Required

Before any future OpenResty route change, record:

- operator and reviewer.
- current git commit.
- current server date.
- `sha256sum` of OpenResty files to be touched.
- copied backup path for each file to be touched.
- `openresty -t` or `nginx -t` result.
- public browser baseline for `/signin`, `/apps`, and an existing Dify app.

## Sidecar Rollback Commands

Run only from the versioned deployment directory:

```bash
docker compose -p openclaw-video -f docker-compose.openclaw-video.yaml ps
docker compose -p openclaw-video -f docker-compose.openclaw-video.yaml down
```

The compose project must not include Dify services, so this must not restart
`docker-api-1`, `docker-web-1`, or `docker-nginx-1`.

## Route Rollback

If an independent OpenResty include file was added, remove only that include or
route file, then test syntax:

```bash
openresty -t
```

Only after syntax passes in a maintenance-approved window:

```bash
openresty -s reload
```

## Post-rollback Verification

Required:

- `/signin` works through public browser.
- `/apps` works through public browser.
- existing Dify app opens.
- existing Dify app sends a message and receives a response.
- `/openclaw-lab/` is no longer routed.
- OpenClaw Gateway and Postgres remain inaccessible from public network.

