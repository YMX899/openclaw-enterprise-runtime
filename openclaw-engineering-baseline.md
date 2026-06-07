# OpenClaw Engineering Baseline

Date: 2026-06-07 Asia/Shanghai

This document is the current execution baseline for the OpenClaw x Dify
short-video integration. It supersedes older notes that required web GPT
review, Dify web login, Douyin account login, or
`REAL_SAMPLE_EVIDENCE.json` before development or root-server testing.

## Current Execution Policy

- Web GPT/ChatGPT review is not required before implementation, deployment, or
  root-server testing.
- Web review is optional only for major architecture disputes, release/security
  sign-off, or an explicit user request.
- Direct root-server deployment and testing are allowed when the change is
  reversible and does not restart, rebuild, or recreate existing Dify
  containers.
- Development gates are relaxed for root testing. Do not block on historical
  Phase 1.5/Phase 4 wording when the current production audit and direct
  browser/server checks prove the current scheme.
- Use git for meaningful changes. A dirty worktree may exist during active
  development; a clean worktree is required only before claiming a final
  release checkpoint.
- When work is broad enough to benefit from parallel execution, create or reuse
  focused agents for UI design, implementation, exploration, or verification.
  Agents must receive bounded ownership, must not revert other changes, and
  their results must be reviewed by the root thread before release.

## OpenClaw UI Baseline

- The OpenClaw page is the user's primary product surface, not just a test
  harness.
- Login, chat/conversation, video-link submission, upload checks, post-login
  acceptance and diagnostic output must be visually coherent on the OpenClaw
  page itself.
- Treat UI work as a senior product-design task. The default design standard is
  a polished professional tool surface with at least iOS-level visual care:
  restrained color, clear spacing, readable hierarchy, responsive layout,
  visible state feedback and no awkward overlapping text.
- The page should be screenshot-tested after significant visual changes on both
  desktop and mobile widths.
- A UI/design agent may be asked to act as a top-tier software-company visual
  communication design director: inspect screenshots, critique the product
  purpose, raise 20 UI/visual-design questions, score the interface, iterate,
  and only exit once its internal review is satisfied.
- Preserve automation selectors and API behavior when redesigning UI. Important
  element IDs include `loginAccount`, `loginPassword`, `loginButton`,
  `authStatus`, `identityDiagnostics`, `runPostLoginAcceptance`, `runSelfTest`,
  `runSecurityTest`, `createSession`, `sessionId`, `videoUrl`, `prompt`,
  `readVideoLink`, `submitJob`, `pollJob`, `videoFile`, `uploadJob`,
  `uploadSmoke` and `output`.

## OpenClaw Login Boundary

- The OpenClaw login UI is part of Phase 4 standalone-login acceptance.
- The primary user page is:

```text
https://www.huahuoai.com/ai/openclaw-lab/
```

- Users log in on the OpenClaw page with an OpenClaw-owned account/password
  form.
- Bridge validates submitted account/password server-side against the configured
  business/Dify database identity source.
- Successful login issues only an OpenClaw-owned HttpOnly session.
- Users do not need to log in to Dify Web or Dify admin for this integration.

## Video Link Boundary

- The Douyin-account-login scheme is retired.
- Browser cookies, Douyin storage state, Playwright storage state and Douyin
  account sessions are not part of the production path.
- The active scheme is video link-read mode:

```text
user video link -> Bridge URL guard -> redirect revalidation -> Worker ->
douyin_chong UniversalVideoResolver -> direct video candidates -> model analysis
```

- `artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json` is optional diagnostic
  history, not a blocking gate.
- Runtime model credentials and permissions still need to be valid for deep
  analysis jobs to succeed, but this is a model-configuration concern, not a
  Douyin-login or sample-evidence blocker.
- OpenClaw may expose a logged-in `video-link/read-check` preflight that proves
  URL validation, redirect revalidation, direct candidate resolution, sanitized
  metadata and `model_invoked=false` before a user submits a full analysis job.

## Root Deployment Baseline

- Use the root server for direct deployment/testing when needed.
- Do not modify the Dify compose file for OpenClaw work.
- Do not restart, rebuild, or recreate Dify `api`, `web`, or `nginx`
  containers unless the user explicitly approves a Dify maintenance action.
- OpenClaw remains a sidecar with independent rollback.
- OpenClaw Bridge may be rebuilt/recreated as part of OpenClaw deployment.
- OpenClaw Gateway, Worker and Bridge Postgres must not expose public host
  ports.
- Public browser access must go through OpenResty routes to the Bridge only.
- Secrets, cookies, authorization headers, CSRF values, full environment files,
  model keys, database URLs and private keys must not be printed or recorded.

## Minimum Test Ladder

1. Run local tests that cover the changed surface.
2. Build/upload/deploy the OpenClaw sidecar bundle to root when runtime behavior
   must be validated.
3. Confirm Dify core container IDs and `StartedAt` did not change.
4. Confirm the OpenClaw login page loads at `/ai/openclaw-lab/`.
5. Confirm unauthenticated OpenClaw API fails closed with `401`.
6. Log in through the OpenClaw login UI and run post-login acceptance.
7. Run security negative tests for rejected URLs and inaccessible random
   resources.
8. Run video link-read testing with an explicit video URL when a valid sample
   URL and runtime model configuration are available.
9. Confirm Dify public pages still load and no new obvious 5xx appears in
   checked routes.
10. Commit, push and record sanitized deployment/test evidence.
