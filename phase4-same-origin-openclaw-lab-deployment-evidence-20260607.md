# Phase 4 Same-Origin OpenClaw Lab Deployment Evidence - 2026-06-07

## Scope

This record covers the Phase 4 development deployment of OpenClaw Lab under the Huahuo same-origin path:

```text
https://www.huahuoai.com/openclaw-lab/
https://www.huahuoai.com/openclaw-api/
```

The original Huahuo/Dify user web remains:

```text
https://www.huahuoai.com/ai/?id=4
```

The Dify administration URL is not used as the primary user-web evidence.

## Git And Release

Current deployed commit:

```text
47d07117f8d0fe8c4f12bcea83187db5b34b278b
```

Current deployed tag:

```text
phase4-openclaw-lab-tiny-upload-20260607
```

Deployment bundle:

```text
openclaw-root-private-sidecar-47d07117f8d0.tar.gz
sha256=531a541b788554f505adf5a59b747a462d4141ee0ef7519ff0b584360394b845
```

Server release path:

```text
/app/bin/openclaw-video/releases/47d07117f8d0
/app/bin/openclaw-video/current -> /app/bin/openclaw-video/releases/47d07117f8d0
```

Previous release recorded on server:

```text
/app/bin/openclaw-video/releases/31743f8237e0
record file: /app/bin/openclaw-video/previous-before-47d07117f8d0.txt
```

## Implemented Changes In This Deployment Series

- Added Huahuo frontend identity provider support for OpenClaw Lab.
- Served OpenClaw Lab on the same origin as Huahuo user web so the page can reuse Huahuo frontend login state.
- Added Huahuo `APP-UUID` signing parity with the public frontend.
- Added Huahuo refresh-token retry parity for expired access tokens.
- Added safe identity diagnostics booleans. They report only whether Huahuo login material is present, never the values.
- Added `Tiny Upload` smoke test button in OpenClaw Lab. It uses the same same-origin auth headers, `/openclaw-api/uploads`, async job polling, and result API as normal uploads.

## Server Baseline After Deployment

Dify core containers were not rebuilt or restarted. Post-deployment IDs and start times remained:

```text
/docker-api-1   1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631  2026-01-05T11:17:20.555976179Z
/docker-web-1   62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36  2026-01-05T11:17:19.85303869Z
/docker-nginx-1 8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe  2026-01-05T11:17:20.937420886Z
```

Current OpenClaw sidecar services:

```text
openclaw-video-openclaw-bridge-1         openclaw-video-openclaw-bridge:fast  Up About a minute  127.0.0.1:18181->3000/tcp
openclaw-video-video-analysis-worker-1   openclaw-video-video-analysis-worker Up 3 hours
openclaw-video-openclaw-gateway-1        openclaw-video-openclaw-gateway      Up 5 hours         18789/tcp internal only
openclaw-video-bridge-postgres-1         postgres:15-alpine                   Up 5 hours healthy 5432/tcp internal only
```

Public route checks:

```text
https://www.huahuoai.com/openclaw-lab/        -> 200
https://www.huahuoai.com/openclaw-api/me      -> 401 without Huahuo login material
https://www.huahuoai.com/ai/?id=4             -> 200
```

## Chrome Evidence

Chrome profile: user logged in to Huahuo web.

Huahuo user web regression already passed before OpenClaw deployment:

```text
URL: https://www.huahuoai.com/ai/?id=4
Action: sent a new chat message asking for a simple acknowledgement
Result: message appeared and the AI produced a visible reply
```

OpenClaw same-origin identity passed:

```text
URL: https://www.huahuoai.com/openclaw-lab/
Status: Authenticated
identity diagnostics:
  authenticated=true
  login_material_present=true
  huahuo_access_token_present=true
  huahuo_app_uuid_present=true
  profile_ok=true
  workspace_ok=true
  access_ok=true
  current_workspace_count=1
```

OpenClaw Tiny Upload smoke test passed from the real Chrome page:

```text
create_session -> 201
upload_job     -> 202
poll_job       -> queued then succeeded
job_result     -> 200
result_schema_version=openclaw-video-result.v1
platform=upload
raw_tool_result.tool=openclaw-upload-file-analyzer
uploaded file=tiny-smoke.mp4
```

Observed job:

```text
job_id=33aa3d69-8147-4456-8924-cdf53c979d2b
session_id=b988c32f-c5d7-4267-8f32-ef3965bc5052
video_url_canonical=upload://556ab7dd-246c-4483-a3ec-d8f7c3aca183/tiny-smoke.mp4
status=succeeded
attempt_count=1
result_location=postgres://video_results/33aa3d69-8147-4456-8924-cdf53c979d2b
```

The Bridge log showed the expected sequence without sensitive headers:

```text
GET  /openclaw-lab/ -> 200
GET  /openclaw-api/me -> 200
POST /openclaw-api/sessions -> 201
POST /openclaw-api/uploads -> 202
GET  /openclaw-api/jobs/{job_id} -> 200
GET  /openclaw-api/jobs/{job_id}/result -> 200
```

## Known Limitation

Chrome automation could not complete native local file selection for `D:\DESK\Dify\tmp\sample-videos\mdn-flower.mp4` because the Codex Chrome extension rejected setting local files:

```text
fileChooser.setFiles failed: Not allowed
```

Attempting to inject the 1.1 MB local file into the page exceeded the Chrome automation transport and reset the control channel. This is an automation/tool permission limit, not a Bridge or Worker failure.

The real browser page now includes `Tiny Upload`, which confirms the same OpenClaw upload API, FormData handling, async job polling, Worker processing, and result retrieval. A real local-file UI upload should be re-run after enabling Chrome extension local-file upload permission or by manual user interaction in Chrome.

## Safety Notes

- No original Dify compose file was changed.
- No original Dify container was restarted or rebuilt.
- Gateway token, model API key, Cookie, Authorization value, Huahuo access token, Huahuo refresh token, and full request headers were not recorded in this document.
- OpenClaw Gateway and Bridge Postgres remained internal-only. Browser-visible requests go only to `/openclaw-api/*`.
- The same-origin OpenResty block is managed with explicit markers and can be removed using the rollback script.

## Rollback

Rollback without restarting Dify:

```bash
OPENCLAW_SAME_ORIGIN_CONF=/app/config/openresty/conf/conf.d/huahuoai.com.conf \
OPENCLAW_SAME_ORIGIN_SERVER_NAME=www.huahuoai.com \
bash /app/bin/openclaw-video/current/scripts/rollback_openclaw_lab_same_origin.sh
```

To return the sidecar to the previous release:

```bash
ln -sfn /app/bin/openclaw-video/releases/31743f8237e0 /app/bin/openclaw-video/current
OPENCLAW_VIDEO_ROOT=/app/bin/openclaw-video/current/openclaw-video \
bash /app/bin/openclaw-video/current/scripts/root_rebuild_bridge_fast.sh
```

The rollback path does not require rebuilding or restarting original Dify containers.
