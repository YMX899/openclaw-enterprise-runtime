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

## Parallel Regression Evidence

After the initial same-origin deployment evidence, a parallel browser regression
was executed with two live Chrome tabs:

```text
Tab A: https://www.huahuoai.com/openclaw-lab/
Tab B: https://www.huahuoai.com/ai/?id=4
```

Preconditions:

```text
OpenClaw Lab showed Authenticated.
OpenClaw Lab showed Tiny Upload.
Huahuo user web loaded the chat UI.
```

Parallel actions:

```text
OpenClaw: clicked Tiny Upload.
Huahuo user web: sent "并行回归测试 1780773016416：请回复收到".
```

OpenClaw result:

```text
create_session -> 201
upload_job     -> 202
poll_job       -> queued, then succeeded
job_result     -> 200
job_id=138be9c6-c1b0-4bf7-a27b-be537cc97e98
session_id=58d26134-d1a4-4ee3-91a4-cf2335d0052b
video_url_canonical=upload://7f81bf99-162e-4720-b719-3f4414c7d7e4/tiny-smoke.mp4
result_schema_version=openclaw-video-result.v1
result_location=postgres://video_results/138be9c6-c1b0-4bf7-a27b-be537cc97e98
```

Huahuo user web result:

```text
The message appeared in the real user chat.
The page stopped showing "思考中...".
The AI produced a visible reply beginning with "我是安老师的AI分身。".
```

Post-parallel server baseline:

```text
https://www.huahuoai.com/openclaw-lab/   -> 200
https://www.huahuoai.com/openclaw-api/me -> 401 without login material
https://www.huahuoai.com/ai/?id=4        -> 200
```

Dify core containers were still not rebuilt or restarted:

```text
/docker-api-1   1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631  2026-01-05T11:17:20.555976179Z
/docker-web-1   62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36  2026-01-05T11:17:19.85303869Z
/docker-nginx-1 8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe  2026-01-05T11:17:20.937420886Z
```

Resource snapshot after the parallel run:

```text
openclaw-bridge         0.11% CPU, 52.67 MiB, 5 PIDs
video-analysis-worker   0.00% CPU, 33.33 MiB, 1 PID
openclaw-gateway        0.00% CPU, 438.9 MiB, 18 PIDs
bridge-postgres         3.09% CPU, 36.75 MiB, 6 PIDs
docker-nginx-1          0.00% CPU, 11.74 MiB, 10 PIDs
docker-api-1            0.68% CPU, 4.273 GiB, 61 PIDs
docker-web-1            0.42% CPU, 359.5 MiB, 34 PIDs
```

Log notes:

```text
OpenClaw Bridge showed the expected 201 -> 202 -> 200 -> result 200 sequence.
OpenClaw worker logs did not show new errors.
Dify API logs showed existing plugin/model credential or balance errors around
conversation-name generation, but the Huahuo user-web reply itself succeeded.
This is tracked as an existing Dify/model-configuration risk rather than an
OpenClaw sidecar regression.
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

## Security Negative Test And Identity Probe Update

Additional commits deployed after the initial same-origin evidence:

```text
b910bd4f724515ab7dc215fbd98421c172cef028  phase4-openclaw-security-negative-20260607
833262eb6e4adcca4a46e6ff7c8ad01549dab538  phase4-huahuo-business-expiry-refresh-20260607
84e13d007d33fa6b80b601d4b55c13271013aee3  phase4-huahuo-safe-identity-probe-20260607
```

Current deployed release:

```text
/app/bin/openclaw-video/current -> /app/bin/openclaw-video/releases/84e13d007d33
previous marker: /app/bin/openclaw-video/releases/833262eb6e4a
```

Implemented in this update:

```text
OpenClaw Lab now includes a Security Test button.
Security Test covers random session/job/result 404 checks.
Security Test submits non-allowlisted URL, localhost, and cloud-metadata URL jobs and expects url_rejected.
Huahuo identity lookup now retries when the frontend API returns HTTP 200 with a business status indicating expiry.
Identity diagnostics now include provider_probe safe metadata only.
provider_probe never returns Cookie, Authorization, access token, refresh token, user id, tenant id, mobile, email, or full headers.
```

Local verification:

```text
PYTHONPATH=openclaw-video\src .\.phase1-sandbox\bridge-api-venv\Scripts\python.exe -m unittest discover openclaw-video\tests
Ran 229 tests
Result: OK
Only warning: StarletteDeprecationWarning from the local FastAPI TestClient dependency.
```

Post-update public checks:

```text
http://127.0.0.1:18181/healthz                         -> 200
https://www.huahuoai.com/openclaw-lab/                  -> 200
https://www.huahuoai.com/openclaw-api/me                -> 401 without login material
https://www.huahuoai.com/ai/?id=4                       -> 200
```

Dify core containers were still not rebuilt or restarted:

```text
/docker-api-1   1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631  2026-01-05T11:17:20.555976179Z  running
/docker-web-1   62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36  2026-01-05T11:17:19.85303869Z   running
/docker-nginx-1 8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe  2026-01-05T11:17:20.937420886Z  running
```

Resource snapshot after the update:

```text
openclaw-video-openclaw-bridge-1         0.10% CPU  49.4 MiB   5 PIDs
openclaw-video-video-analysis-worker-1   0.00% CPU  33.33 MiB  1 PID
openclaw-video-openclaw-gateway-1        0.00% CPU  439.2 MiB  18 PIDs
openclaw-video-bridge-postgres-1         0.00% CPU  36.75 MiB  6 PIDs
docker-nginx-1                           0.00% CPU  11.74 MiB  10 PIDs
docker-api-1                             0.78% CPU  4.273 GiB  61 PIDs
docker-web-1                             0.47% CPU  359.9 MiB  34 PIDs
```

Chrome identity probe result after the update:

```text
URL: https://www.huahuoai.com/openclaw-lab/
Action: Identity Check
authenticated=false
login_material_present=false
huahuo_access_token_present=false
huahuo_app_uuid_present=false
profile_ok=false
failure_stage=profile
provider_probe.provider=huahuo_front
provider_probe.identity_headers_present=false
provider_probe.profile_http_status=401
provider_probe.refresh_attempted=true
provider_probe.error_stage=refresh_missing
```

Interpretation:

```text
The current Chrome profile no longer has Huahuo frontend login material available to the same-origin Lab page.
The Huahuo user web also showed the landing/login page after refresh, not the authenticated chat UI.
This blocks authenticated Security Test execution until the user logs in to Huahuo again.
Unauthenticated behavior is correct: /openclaw-api/me returns 401 and Lab cannot create sessions or jobs without identity.
```

Next browser gate:

```text
After Huahuo user login is restored in Chrome, rerun:
1. Identity Check: expect authenticated=true, profile_ok=true, workspace_ok=true, access_ok=true.
2. Security Test: expect random resource checks to return 404 and all negative URL jobs to finish failed/url_rejected.
3. Tiny Upload: expect 202 job creation and succeeded result.
4. Huahuo user web regression: send one short message at https://www.huahuoai.com/ai/?id=4 and confirm reply.
```

Rollback to the previous sidecar release:

```bash
ln -sfn /app/bin/openclaw-video/releases/833262eb6e4a /app/bin/openclaw-video/current
OPENCLAW_VIDEO_ROOT=/app/bin/openclaw-video/current/openclaw-video \
bash /app/bin/openclaw-video/current/scripts/root_rebuild_bridge_fast.sh
```

## Public Smoke Target Refresh

Date: 2026-06-07T03:45-03:47+08:00.

The public smoke script was updated to use the current Huahuo/Dify entry points:

```text
OpenClaw Lab:             https://www.huahuoai.com/openclaw-lab/
OpenClaw unauth API:      https://www.huahuoai.com/openclaw-api/me
Huahuo user web:          https://www.huahuoai.com/ai/?id=4
Dify admin configuration: https://ai001.huahuoai.com/app/d44c1add-5043-4b33-b513-1d4f6ec3b4f0/configuration
```

Local tests:

```text
PYTHONPATH=openclaw-video\src .\.phase1-sandbox\bridge-api-venv\Scripts\python.exe -m unittest discover openclaw-video\tests
Ran 229 tests
Result: OK
Only warning: StarletteDeprecationWarning from the local FastAPI TestClient dependency.
```

Public Playwright smoke:

```text
Command: python scripts\run_public_browser_smoke.py --timeout-seconds 90
Run dir: tmp\playwright-public-browser\20260606T194526Z
Overall: PASS
Secrets recorded in summary: false
Headers recorded in summary: false
Bodies recorded in summary: false
```

Smoke targets:

```text
https://www.huahuoai.com/openclaw-lab/                                      -> 200, passed
https://www.huahuoai.com/openclaw-api/me                                    -> 401, passed
https://www.huahuoai.com/ai/?id=4                                           -> 200, passed
https://ai001.huahuoai.com/app/d44c1add-5043-4b33-b513-1d4f6ec3b4f0/configuration -> 200, passed
```

Smoke safety checks:

```text
http_5xx_count: 0
gateway_direct_request_count: 0
token_url_leak_count: 0
```

Root server read-only baseline:

```text
time=2026-06-07T03:46:54+08:00
current=/app/bin/openclaw-video/releases/84e13d007d33
same_origin_lab=200
same_origin_me_unauth=401
huahuo_user_ai=200
huahuo_admin_config=403
```

Dify core containers were still not rebuilt or restarted:

```text
/docker-api-1   1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631  2026-01-05T11:17:20.555976179Z  running
/docker-web-1   62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36  2026-01-05T11:17:19.85303869Z   running
/docker-nginx-1 8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe  2026-01-05T11:17:20.937420886Z  running
```

Root resource snapshot:

```text
openclaw-video-openclaw-bridge-1         0.10% CPU  51.51 MiB  5 PIDs
openclaw-video-video-analysis-worker-1   0.00% CPU  33.33 MiB  1 PID
openclaw-video-openclaw-gateway-1        0.00% CPU  439.3 MiB  18 PIDs
openclaw-video-bridge-postgres-1         0.00% CPU  36.75 MiB  6 PIDs
docker-nginx-1                           0.00% CPU  11.74 MiB  10 PIDs
docker-api-1                             0.68% CPU  4.273 GiB  61 PIDs
docker-web-1                             0.39% CPU  366 MiB   34 PIDs
```

The raw server `curl` to the admin configuration URL returned `403`, while the real-browser Playwright public smoke reached the route with a `200` top-level document. This is recorded as an access-policy difference between browser navigation and bare server-side `curl`; the browser route remains the acceptance reference for the admin page.

Chrome status:

```text
OpenClaw Lab URL: https://www.huahuoai.com/openclaw-lab/
Lab visible state: Login Required
Huahuo user URL after navigation: https://www.huahuoai.com/home/
Huahuo user visible state: landing page with login action, not authenticated chat
Dify admin URL: https://ai001.huahuoai.com/app/d44c1add-5043-4b33-b513-1d4f6ec3b4f0/configuration
Dify admin visible state: authenticated configuration UI, title "模型测试 - Dify"
```

Chrome Identity Check:

```text
authenticated=false
login_material_present=false
huahuo_access_token_present=false
huahuo_app_uuid_present=false
profile_ok=false
workspace_ok=false
access_ok=false
failure_stage=profile
provider_probe.provider=huahuo_front
provider_probe.identity_headers_present=false
provider_probe.profile_http_status=401
provider_probe.refresh_attempted=true
provider_probe.error_stage=refresh_missing
```

Interpretation:

```text
The Dify admin session at ai001.huahuoai.com is currently valid in Chrome.
The Huahuo user-web session at www.huahuoai.com is currently not valid in Chrome.
The same-origin OpenClaw Lab intentionally fails closed when the Huahuo user-web login material is absent.
No Cookie, Authorization header, access token, refresh token, full request header, or localStorage value was inspected or recorded.
```

Pending authenticated browser gate:

```text
After the Huahuo user web is logged in again at https://www.huahuoai.com/ai/?id=4:
1. Identity Check must return authenticated=true.
2. Security Test must pass random resource isolation and negative URL rejection.
3. Tiny Upload must return a succeeded async job.
4. A Huahuo user-web chat message must still reply normally while OpenClaw is available.
```
