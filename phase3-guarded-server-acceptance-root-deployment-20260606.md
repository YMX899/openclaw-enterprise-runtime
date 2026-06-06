# Phase 3 Guarded Server Acceptance Root Deployment Evidence

Date: 2026-06-06

## Decision Update

The deployment gate is relaxed for the OpenClaw sidecar path: most OpenClaw Bridge, Lab, Gateway adapter, worker, and acceptance-test development can proceed directly on the root server when the change remains versioned, reversible, and isolated from the existing Dify runtime.

The still-protected boundary is unchanged:

- Do not rebuild or restart the original Dify `docker-api-1`, `docker-web-1`, or `docker-nginx-1` containers for OpenClaw sidecar changes.
- Do not modify the Dify compose project for OpenClaw sidecar iteration.
- Keep OpenClaw Lab on an independent public port, currently `18443`, not on the same public web port as Dify.
- Keep Bridge bound to `127.0.0.1:18181`; only OpenResty exposes the independent public Lab port.
- Keep OpenClaw Gateway and Bridge Postgres off the public host surface.

## Version

- Git commit: `534410f6478e3a137e8084e2798ad8b09ce93c0e`
- Git tag: `phase3-guarded-server-acceptance-20260606`
- Bundle: `openclaw-root-private-sidecar-534410f6478e.tar.gz`
- Bundle SHA256: `06258ecb938f3d11ddc71a943dc1d15d9a6e11e305943e383fd968ea34743720`
- Root release: `/app/bin/openclaw-video/releases/534410f6478e`
- Current symlink: `/app/bin/openclaw-video/current -> /app/bin/openclaw-video/releases/534410f6478e`

## Deployment Notes

The release bundle was uploaded to the root server, SHA256 verified, and extracted into a versioned release directory.

The Bridge was rebuilt with the fast Bridge rebuild script:

```text
OPENCLAW_VIDEO_ROOT=/app/bin/openclaw-video/current/openclaw-video bash /app/bin/openclaw-video/current/scripts/root_rebuild_bridge_fast.sh
```

Only `openclaw-video-openclaw-bridge-1` was recreated. The original Dify containers remained up and were not restarted.

Current relevant containers after deployment:

```text
openclaw-video-openclaw-bridge-1         Up, 127.0.0.1:18181->3000/tcp
openclaw-video-video-analysis-worker-1   Up
openclaw-video-openclaw-gateway-1        Up, internal 18789/tcp
openclaw-video-bridge-postgres-1         Up healthy, internal 5432/tcp
docker-nginx-1                           Up 5 months
docker-api-1                             Up 5 months
docker-web-1                             Up 5 months, historical unhealthy healthcheck baseline
```

## Guarded Test Identity

To support direct root-server acceptance without a logged-in browser session, the Bridge now supports a guarded test identity path.

The test identity path is disabled by default and requires both:

```text
BRIDGE_ENABLE_TEST_IDENTITY_HEADERS=1
BRIDGE_TEST_IDENTITY_SECRET=<one-time secret>
```

The request must include `x-openclaw-test-identity-secret`. The secret comparison is constant-time and the secret is not returned by any Bridge endpoint.

Server acceptance temporarily enabled this path, ran the checks, and then restored:

```text
BRIDGE_ENABLE_TEST_IDENTITY_HEADERS=0
BRIDGE_TEST_IDENTITY_SECRET=
```

Post-restore verification:

```text
post_restore_diag=authenticated=False failure=profile
bridge_env_test_mode=BRIDGE_ENABLE_TEST_IDENTITY_HEADERS=0
bridge_secret_env_present=0
```

## Server Acceptance Result

Acceptance artifact on root:

```text
/tmp/openclaw-bridge-acceptance-534410f6478e.json
```

Result:

```text
overall=PASS
test_identity_secret_present=PASS provided
unauthenticated_me=PASS status=401
diagnostics_authenticated=PASS status=200 authenticated=True
me_authenticated=PASS status=200 principal_len=64
create_session=PASS status=201
cross_user_session_404=PASS status=404
create_invalid_url_job=PASS status=202
cross_user_job_404=PASS status=404
invalid_url_job_rejected=PASS status=failed error=url_rejected
messages_visible_to_owner=PASS status=200 count=1
```

This verifies:

- unauthenticated API rejection,
- diagnostics with hashed principal only,
- session creation,
- owner-only message access,
- cross-user session isolation,
- async job creation,
- cross-user job isolation,
- invalid non-Douyin URL rejection by the worker path,
- owner-visible messages after job submission.

## Public Baseline

Public OpenClaw Lab independent port:

```text
https://ai001.huahuoai.com:18443/openclaw-lab/ -> 200
https://ai001.huahuoai.com:18443/openclaw-api/identity/diagnostics -> authenticated=False, failure=profile
https://ai001.huahuoai.com:18443/openclaw-api/me -> 401
```

Public Dify baseline:

```text
https://ai001.huahuoai.com/signin -> 200
https://ai001.huahuoai.com/apps -> 200
https://ai001.huahuoai.com/console/api/account/profile -> 401 unauthenticated
```

Host port surface:

```text
0.0.0.0:18443  openresty independent OpenClaw Lab public port
127.0.0.1:18181 openclaw-bridge host loopback only
no host 5432 listener for bridge-postgres
no host 18789 listener for openclaw-gateway
```

## Rollback

Rollback remains version based and does not require rebuilding or restarting Dify containers.

Fast rollback to the previous Bridge release:

```text
ln -sfn /app/bin/openclaw-video/releases/01ddff9bd500 /app/bin/openclaw-video/current
OPENCLAW_VIDEO_ROOT=/app/bin/openclaw-video/current/openclaw-video \
  BRIDGE_ENABLE_TEST_IDENTITY_HEADERS=0 \
  BRIDGE_TEST_IDENTITY_SECRET= \
  bash /app/bin/openclaw-video/current/scripts/root_rebuild_bridge_fast.sh
```

Public route rollback remains independent:

```text
/app/bin/openclaw-video/current/scripts/uninstall_openclaw_lab_public_port.sh
```

After either rollback path, re-check:

```text
https://ai001.huahuoai.com/signin
https://ai001.huahuoai.com/apps
https://ai001.huahuoai.com/console/api/account/profile
```

## Remaining Gaps

- Real logged-in browser flow still needs a successful Chrome/plugin run or manual browser evidence.
- Real Douyin sample analysis still needs a real public sample URL run through the worker.
- Network-panel verification must still confirm no Gateway token appears in browser traffic during a logged-in session.
