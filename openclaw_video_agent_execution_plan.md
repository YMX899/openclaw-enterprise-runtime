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

The active scheme is video link-read mode:

```text
user video link
-> Bridge URL guard
-> redirect revalidation
-> Worker
-> douyin_chong UniversalVideoResolver
-> direct video candidates
-> model-backed analysis
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
