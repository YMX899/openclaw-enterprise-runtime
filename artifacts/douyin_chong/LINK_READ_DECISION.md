# Douyin Link-Read Mode Decision

Date: 2026-06-07 Asia/Shanghai

Status: adopted production-readiness scope change.

## Decision

```text
link_read_mode: ADOPTED
REAL_SAMPLE_EVIDENCE.json: NOT_REQUIRED
douyin_account_login: NOT_REQUIRED
browser_storage_state: NOT_REQUIRED
runtime_path: url_guard -> worker_service -> douyin_legacy_adapter -> UniversalVideoResolver
allowlisted_douyin_hosts: PASS
redirect_revalidation: PASS
private_ip_blocking: PASS
no_browser_login_state: PASS
```

OpenClaw no longer treats Douyin account login, Douyin browser storage state, or
`artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json` as production readiness
requirements. The V1 route accepts a user-provided video link, validates the
link through the URL guard, resolves any allowlisted Douyin redirect chain, and
passes the canonical link into the worker adapter.

## Runtime Path

The active runtime path is:

```text
Bridge receives video_url
openclaw_video.url_guard.validate_video_url_with_redirects
openclaw_video.worker_service.VideoAnalysisWorker
openclaw_video.douyin_legacy_adapter.run_adapter
douyin_chong.clients.resolver.UniversalVideoResolver
resolved direct video URL candidates
ArkVideoClient video analysis
openclaw-video-result.v1
```

This path uses link resolution and direct video URL candidates exposed by the
resolver. It does not load browser cookies, Douyin login state, Playwright
storage state, or a Douyin account session.

## Scope Boundary

This decision removes the production gate that required a committed sanitized
real-sample evidence file. It does not remove the runtime need for valid model
configuration when deep video analysis is enabled. If the configured model key
or model permission is invalid, video analysis can still fail at runtime with a
tool failure, but that is no longer a blocker tied to a Douyin login strategy or
to `REAL_SAMPLE_EVIDENCE.json`.

## Safety Requirements

- Only HTTP and HTTPS video links are accepted.
- Hosts must remain limited to the Douyin allowlist.
- Redirect targets are revalidated on every hop.
- Private, loopback, link-local, metadata, multicast, unspecified and reserved
  IP addresses are rejected.
- URL userinfo is rejected.
- Runtime secrets stay in the explicit worker secret file and are not committed.
- Vendored `douyin_chong` source must not include `.env`, `.env.local`,
  `.douyin_storage_state*.json`, login-state utilities, cookies, token files,
  generated captures, or browser session artifacts.

## Operational Note

The historical real-sample runner and promotion helper remain available as
optional troubleshooting tools. They are not part of the current production
readiness gate after this scheme change.
