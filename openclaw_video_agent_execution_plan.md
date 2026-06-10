# OpenClaw Video Agent Execution Plan

Date: 2026-06-08 Asia/Shanghai

This file is the current execution document. It replaces the older Dify-Web
entry, Douyin account-login, cookie, browser-storage-state, and
`REAL_SAMPLE_EVIDENCE.json` gate plan.

## Current Goal

Build and operate an OpenClaw-owned short-video analysis surface on the Huahuo
web domain without requiring the user to log in to Dify Web.

Primary user entry:

```text
https://www.huahuoai.com/ai/openclaw-lab/
```

The OpenClaw page owns:

- account/password login UI.
- session creation.
- video link read check.
- video analysis job submission.
- upload fallback.
- conversation/status/result presentation.
- diagnostics and post-login acceptance tools.

Dify Web remains independent. Whether the Dify Web page is logged in is not a
gate for this OpenClaw page.

## Login Boundary

Current login scheme:

```text
user account/password
-> OpenClaw login form
-> Bridge server-side credential validation
-> OpenClaw-owned HttpOnly session
-> OpenClaw API access
```

Rules:

- Do not depend on Dify Web login state.
- Do not require Dify admin/login browser sessions.
- Do not use browser cookies as a bridge between Dify Web and OpenClaw.
- Do not record account, password, cookie, header, token, database URL, or
  secret file contents in docs, screenshots, logs, or evidence.
- Test account material is operational input only and must not be copied into
  persistent engineering evidence.

## Video Analysis Boundary

### Direction update 2026-06-10 (user-confirmed)

Doubao 2.0 (`doubao-seed-2-0-pro`) can analyze a video **directly from a video
URL**. We do not download the user's video and then analyze frames locally.
The product therefore supports exactly two input methods, both ending in a
single Doubao-from-URL analysis call:

1. **Video link** — user pastes a share/video link.
2. **Video file upload** — user uploads a local video file.

Flow contract (both methods):

```text
user sends video link OR uploads a video file
-> OpenClaw agent recognizes a video input and calls the analysis tool
-> the tool produces a Doubao-fetchable video URL
     - link: Bridge URL guard -> redirect revalidation ->
       douyin_chong UniversalVideoResolver -> direct CDN video URL
     - upload: stored file is exposed as a Doubao-fetchable video URL
-> ArkVideoClient.analyze(video_urls=[...]) — Doubao reads the URL directly
-> structured analysis result returned to the conversation
```

Key points:

- No "download the whole file, extract frames, then analyze" step. The model
  reads the video from the URL itself. Any local byte read is only a bounded
  safety probe (size/duration guard), not a precondition for analysis.
- The Bridge URL guard + redirect revalidation stay — they are a **security
  control** (SSRF/private-network/metadata defense), not a download step.
- For douyin share links the resolver is still required, because a share link
  is an HTML page, not a direct video URL Doubao can fetch.
- For uploads, the open item is exposing the stored file as a URL the Volcano
  Ark API can fetch (the upload path is currently a file-level-validation
  placeholder and does not yet run a real Doubao analysis).
- The agent only decides "this turn carries a video input -> call the tool";
  it does not read or transcode the video itself. Rule-based detection and the
  worker pipeline remain on the Bridge side.

**Immediate task (this round, user-confirmed 2026-06-10):** prove the **link
method** end-to-end on root — user pastes a real douyin link, the tool resolves
it, Doubao analyzes from the resolved URL, and the structured result is returned
into the conversation. **Update 2026-06-10:** the **upload method** now also runs
a real Doubao analysis — the worker inline-base64s the uploaded file into a
`data:` URL and Doubao analyzes it directly (no public hosting; size-guarded by
`MAX_INLINE_UPLOAD_BYTES`, oversize → `upload_too_large`). Verified end-to-end on
root (28.6MB mp4 → `succeeded`, 1936-char analysis). Evidence:
`artifacts/evidence/phase4/openclaw-upload-real-analysis-root-evidence-20260610.json`.
Both input methods (link + upload) are now complete.

### Root test finding 2026-06-10 (link path)

Ran the link path end-to-end on root with a real douyin share link
(`v.douyin.com/...`). Result: the API plumbing is healthy but real analysis
fails at the **resolver** layer.

- Healthy: OpenClaw login `200`, `/me` `200`, create session `201`,
  read-check `200`, job submit `202`, queue + worker pickup all work.
- Read-check returned `status=WARN`: resolver produced `video_id` + 2 direct
  candidates, but `duration_seconds=0.0`, `size_known=false`,
  `eligible_for_model_analysis=false`.
- Job failed in ~5s with `error_code=tool_failed`. Adapter stderr:
  `video size is unavailable` — the local streaming size probe
  (`_probe_stream_size_bytes` in `_enforce_limits`) could not read the
  candidate URL.
- Bypassing the size probe and calling Doubao directly returned
  `400 InvalidParameter (param: video_url)` — Doubao's own fetch of the
  candidate URL failed.
- Reachability probe of both candidates: host `aweme.snssdk.com`, DNS + TCP
  443 OK, but HTTP `404 Not Found`. `content_type=None`, `duration_ms=0`.

Root cause: the vendored `douyin_chong` `UniversalVideoResolver` returns a
degraded douyin detail response (a `play_addr` whose `url_list[0]` 404s, no
duration). This is douyin web-API / anti-bot signature drift, **not** a Bridge,
worker, or Doubao limitation. Doubao-from-URL works only when the resolver
yields a publicly fetchable direct video URL; for this link it does not.

Removing the local size-probe download (per the direction above) is still
correct but is **not sufficient** — Doubao cannot fetch a 404 URL either. The
real blocker is restoring correct douyin link resolution. Decision pending with
the user on how to proceed (fix/refresh resolver signing, use a maintained
parsing path, and/or prioritize the upload path which sidesteps douyin
resolution).

Follow-up test (does Doubao fetch the douyin link itself?): the user noted that
Doubao should be able to take a video link directly. Tested all three readings
against the deployed Ark `chat.completions` `video_url` path, same link:

1. resolver direct URL (`aweme.snssdk.com`) as `video_url` → `400`, candidate
   `404`.
2. raw share link (`v.douyin.com/...`) and redirect-expanded
   (`www.douyin.com/video/...`) as `video_url` → `400 InvalidParameter`,
   message `Error while connecting: ... status code 444`. Doubao's fetcher
   reaches douyin but douyin returns HTTP `444` (anti-bot connection close).
3. link as plain text in the prompt (no `video_url` part) → model replies
   "我无法访问该抖音视频链接对应的内容" — chat.completions does not browse.

Consolidated root cause: **douyin anti-bot blocks programmatic access to the
video stream — including Doubao's own server-side fetch (HTTP 444).** Doubao has
no special ability to fetch douyin links via this path despite the shared
ByteDance ownership. The link path therefore needs something that defeats
douyin anti-bot to produce a clean Doubao-fetchable URL (the resolver's job,
currently broken). The **upload path has no anti-bot wall** and is the most
reliable route to a working analysis. (If a different Doubao video-understanding
endpoint that natively accepts douyin links exists, that would change this —
not the case for the deployed Ark chat.completions path.)

### CORRECTED CONCLUSION 2026-06-10 (the earlier "resolver broken / anti-bot wall" was wrong)

After reading the user's working reference project `D:\DESK\视频解析\源文件\tik`
(`douyin_chong`, the upstream of our vendored copy) and isolating link types on
root, the real situation is:

- **Regular douyin `/video/` links already work end-to-end on root.** Tested the
  DEPLOYED vendored resolver against `www.douyin.com/video/7590677612922457363`:
  it resolved `duration=39846ms`, `video/mp4`, `9.28MB`, **a real
  `douyinvod.com` CDN direct URL**, and Doubao returned a full 1564-char Chinese
  analysis directly from that URL (tier-1, no fallback). The deployed pipeline is
  NOT broken for videos.
- **The user's test link `8KDNVUWc7dE` is NOT a video.** It canonicalizes to
  `www.douyin.com/note/7648723208791056627`, and the note SSR payload shows
  `aweme_type=2` (douyin **图文 / image-text post**), `images` present,
  `video.duration=0`, desc `#今日穿搭灵感 #ootd女生穿搭 …`. It is an OOTD image
  slideshow with background music — there is no video stream to analyze, which is
  why every video path failed for it (the `aweme.snssdk.com` play endpoint 4xx’s
  because there is no real video; for true videos that endpoint 302-redirects to
  `douyinvod.com`).
- The earlier "Timeout/444/404" results were all artifacts of feeding a 图文
  note (or its HTML page) into a video path. They do **not** indicate a resolver
  regression or an anti-bot wall for normal videos.
- "照搬" the reference would not fix this link: the reference resolver is
  video-only and does not even extract a `/note/` id; our deployed copy is
  actually slightly newer (has `/note/` id handling) yet still cannot produce a
  video for a 图文.

Net: the link path for normal douyin videos is healthy. The real gap is
**图文 (image-text) note support**, which needs a different path — send the note's
`images[].url_list` as `image_url` content parts to Doubao (image analysis),
not `video_url` (video analysis). The reference project's value for us is the
**inline base64 fallback** (download bytes ourselves → `data:` URL) for the rare
case where Doubao cannot fetch a valid CDN URL — a robustness add-on, not the
fix for this link.

My root testing did not restart/rebuild any Dify core container
(`docker-api-1`/`web-1`/`nginx-1`).

### Link path VERIFIED end-to-end on root 2026-06-10

With a real douyin **video** link (user-provided, canonical
`/video/7648881101351999931`, 33s, 6.04MB), the full product flow succeeded
through the real OpenClaw API: login `200` → `/me` `200` → create session `201`
→ read-check `PASS` (eligible_for_model_analysis=true) → submit job `202` →
`queued → running → succeeded` (~45s) → result `200`
(`schema_version=openclaw-video-result.v1`, `platform=douyin`,
`summary_len=1065`, a full structured Chinese analysis). Reproduced across three
consecutive runs. Public routes stayed `200/200/401` and Dify core container
ids/StartedAt were unchanged. Sanitized evidence:
`artifacts/evidence/phase4/openclaw-real-video-link-e2e-root-evidence-20260610.json`.

Conclusion: the douyin **video**-link analysis path is working and verified.
Remaining (separate, optional) work: **图文 (image-text) note support** via an
`image_url` path, and the **inline base64 fallback** robustness add-on from the
reference project.

### Active scheme (security + resolution detail)

The active scheme is video link-read / direct-URL mode:

```text
user video link
-> Bridge URL guard
-> redirect revalidation
-> Worker
-> douyin_chong UniversalVideoResolver
-> direct video candidates
-> Doubao analysis directly from the resolved URL
```

Retired scheme:

- Douyin account login.
- Douyin browser cookie reuse.
- Playwright/browser storage state.
- mandatory `artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json` promotion.

`artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json` is no longer a blocker. If
present, it is only optional historical diagnostic evidence.

Runtime model credentials are configured on root through secret files. The repo
must only record that required keys are present, never their values.

## UI Standard

The OpenClaw page is a product surface, not a temporary workbench. The design
standard is a polished professional tool UI with at least iOS-level care:

- clear current/done/locked/error/pass state model.
- one dominant CTA for the current step.
- diagnostics and raw JSON treated as secondary operator details.
- desktop and mobile layouts without overlap or horizontal overflow.
- visible status must match acceptance evidence after login/session/acceptance.
- no scary red state for ordinary "not signed in yet" states.

UI work order:

1. Finish implementation and design review by code/screenshot evidence.
2. Commit the UI changes.
3. Deploy to root.
4. Run root browser/API acceptance.
5. Capture root desktop/mobile screenshots and sanitized JSON evidence.

Do not run local browser/test loops for this phase unless the user explicitly
asks for local testing.

## Root-First Deployment Policy

The root server is the authoritative environment for this stage.

Allowed:

- direct root deployment/testing for OpenClaw sidecar changes.
- rebuilding/recreating OpenClaw Bridge when deploying a reversible OpenClaw
  release.
- root-side browser/API acceptance after UI debug is complete.

Not allowed without explicit user approval:

- restarting, rebuilding, or recreating Dify `api`, `web`, or `nginx`.
- modifying Dify compose for OpenClaw.
- exposing OpenClaw Gateway, Worker, or Bridge Postgres directly to the public
  network.

Required invariants after deployment:

- Dify root page returns 200.
- OpenClaw page returns 200.
- unauthenticated OpenClaw API returns 401.
- Dify `api`, `web`, and `nginx` container IDs and `StartedAt` stay unchanged.
- rollback release marker is recorded.

## Current Evidence Anchors

Latest iOS-grade UI root deployment evidence (release
`video-agent-fix-20260608T0001`, commit `f553e65`, tag
`phase4-openclaw-ui-ios-grade-polish-20260608`):

```text
artifacts/evidence/phase4/openclaw-ui-ios-grade-root-deployment-evidence-20260608.json
artifacts/evidence/phase4/openclaw-ui-ios-grade-root-desktop-20260608.png
artifacts/evidence/phase4/openclaw-ui-ios-grade-root-mobile-20260608.png
```

Prior productized UI root evidence (release `c9aaaa8c6655`):

```text
artifacts/evidence/phase4/openclaw-productized-ui-root-deployment-evidence-20260607.json
artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json
artifacts/evidence/phase4/openclaw-ui-productized-root-desktop-20260607.png
artifacts/evidence/phase4/openclaw-ui-productized-root-mobile-20260607.png
artifacts/evidence/phase4/openclaw-chrome-readonly-review-20260607.json
```

Current real video analysis root evidence:

```text
artifacts/evidence/phase4/openclaw-real-video-analysis-root-evidence-20260607.json
```

Current engineering baseline:

```text
openclaw-engineering-baseline.md
openclaw-video/README.md
artifacts/evidence/phase4/
```

## Current Status

Completed on 2026-06-08:

- The OpenClaw lab UI was upgraded to an iOS-grade visual standard
  (design-token foundation, 44px+ tap targets, branded focus rings, custom
  scrollbars, chat-bubble tails, richer landing hero). The change is CSS and
  landing markup only; all element IDs and JS-toggled state classes were
  preserved. Committed as `f553e65`, tagged
  `phase4-openclaw-ui-ios-grade-polish-20260608`, pushed to origin, deployed to
  root by rebuilding only the OpenClaw Bridge, and verified live: Huahuo root
  200, OpenClaw page 200, unauthenticated API 401, zero horizontal overflow at
  1440/390, WCAG AA contrast on measured text, Chinese title intact, and Dify
  api/web/nginx container IDs and StartedAt unchanged.
- The in-flight video-agent adapter work was finalized and audits synced:
  `agent_video_cli` command-line tool, redirect canonicalization and streaming
  size probe in the adapter, douyin resolver `/note/` support and multi-URL
  fallback, vendored `SOURCE_SHA256SUMS` resync, and updated
  production-readiness audit string assertions. All affected tests pass and the
  production-readiness audit returns GO. Committed as `c8218e5`, tagged
  `phase4-openclaw-video-agent-finalize-20260608`. This work is already running
  on root release `video-agent-fix-20260608T0001`.

Completed on 2026-06-07:

- Productized OpenClaw UI implementation, root deployment, desktop/mobile
  evidence and post-login acceptance for root release `c9aaaa8c6655`.
- The OpenClaw-owned login gate is active; the retired Dify Web login baseline
  and `REAL_SAMPLE_EVIDENCE.json` promotion path have been removed from current
  audits.
- Real-video analysis evidence was refreshed through the deployed OpenClaw API;
  job prefix `afa95a9f` succeeded with `openclaw-video-result.v1`, sanitized
  evidence committed in
  `artifacts/evidence/phase4/openclaw-real-video-analysis-root-evidence-20260607.json`.
- Text chat through the OpenClaw Gateway agent (Doubao provider) is working on
  root: the Bridge backend device is paired and `POST /openclaw-api/chat`
  returns 200.

## Remaining Work

1. Keep the productized UI aligned with the visual-review requirements during
   future feature changes.
2. Push the `c8218e5` video-agent-finalize commit and its tag to origin when the
   user approves a remote push (the UI commit `f553e65` is already on origin).
3. Investigate the single known pre-existing unit-test failure
   `test_identity_diagnostics_fails_closed_for_multiple_current_workspaces`,
   which predates the UI and video-agent work and is unrelated to either.

## Deletion Policy For Old Files

Old documents and evidence that still imply the retired Dify Web login,
Douyin-account-login, cookie, browser storage state, or
`REAL_SAMPLE_EVIDENCE.json` blocker may be deleted or rewritten when they are
not used by current code or current audits.

Current code, deployment scripts, current root evidence, security decisions,
runtime contracts, and rollback records must not be deleted casually.
