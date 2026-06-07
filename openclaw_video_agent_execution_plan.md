# OpenClaw Video Agent Execution Plan

Date: 2026-06-07 Asia/Shanghai

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

Current productized UI root evidence:

```text
artifacts/evidence/phase4/openclaw-productized-ui-root-deployment-evidence-20260607.json
artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json
artifacts/evidence/phase4/openclaw-ui-productized-root-desktop-20260607.png
artifacts/evidence/phase4/openclaw-ui-productized-root-mobile-20260607.png
```

Current real video analysis root evidence:

```text
artifacts/evidence/phase4/openclaw-real-video-analysis-root-evidence-20260607.json
```

Current engineering baseline:

```text
openclaw-engineering-baseline.md
openclaw-video/README.md
phase4-same-origin-openclaw-lab-deployment-evidence-20260607.md
```

## Remaining Work

1. Keep the productized UI aligned with the visual-review requirements.
2. Deploy the latest UI revision to root after code/design review.
3. Capture fresh root UI acceptance evidence for the latest release.
4. Re-run real video analysis on the latest deployed release after the user
   provides a test video link or explicitly confirms which link to reuse.
5. Commit, tag, push, and record sanitized final evidence.

## Deletion Policy For Old Files

Old documents and evidence that still imply the retired Dify Web login,
Douyin-account-login, cookie, browser storage state, or
`REAL_SAMPLE_EVIDENCE.json` blocker may be deleted or rewritten when they are
not used by current code or current audits.

Current code, deployment scripts, current root evidence, security decisions,
runtime contracts, and rollback records must not be deleted casually.
