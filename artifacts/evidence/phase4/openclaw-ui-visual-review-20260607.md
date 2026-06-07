# OpenClaw UI Visual Review Evidence

Date: 2026-06-07 Asia/Shanghai

Scope: OpenClaw public page at `https://www.huahuoai.com/ai/openclaw-lab/`.

This sanitized note records the UI review that led to the current Chinese
landing-page plus post-login chat-workspace redesign. It does not record
cookies, local storage, account values, passwords, API keys, request headers,
raw video URLs or model output.

## Review Inputs

- Desktop baseline screenshot:
  `artifacts/evidence/phase4/openclaw-review-desktop-20260607.png`
- Mobile baseline screenshot:
  `artifacts/evidence/phase4/openclaw-review-mobile-20260607.png`
- Page source: `openclaw-video/src/openclaw_video/bridge_app.py`

## Current Product Decision

The OpenClaw page is no longer treated as an English engineering workbench. The
current UI direction is:

1. The first page is a Chinese product-introduction page explaining what
   OpenClaw can do.
2. The only top-right entry on the first page is `登录`.
3. The login form belongs to OpenClaw and is independent from Dify Web login
   state.
4. After successful login, the page switches into a normal Chinese chat
   workspace.
5. The chat workspace includes new conversation, historical conversation list,
   conversation refresh, chat composer, video link analysis, upload fallback,
   result status and secondary diagnostics.

## Top Issues Found In The Baseline UI

1. The old first viewport looked like an internal operator console rather than
   a product entry page.
2. The old header showed runtime state before the user understood the product.
3. The login form occupied the first screen instead of acting as a deliberate
   entry point.
4. The top area carried multiple controls and statuses before authentication.
5. The visual language was English-first while the required product language is
   Chinese.
6. The page did not explain the product value before asking the user to act.
7. The old flow exposed implementation steps too early.
8. Conversation history was not a primary navigation surface.
9. New conversation was a workflow step instead of a natural chat action.
10. The chat area looked more like a log panel than a normal conversation UI.
11. Video analysis controls competed with login and session controls.
12. Diagnostics had too much weight for a normal user workflow.
13. Raw JSON was still visually close to primary output.
14. Mobile first view was too dense and too operational.
15. The old page did not satisfy the requirement that only login appears in the
    top-right first-page controls.
16. Visual hierarchy was functional but not yet at a polished vendor-site
    level.
17. The result panel duplicated state labels without a strong user narrative.
18. Button copy mixed product and diagnostic terminology.
19. The old screenshot did not communicate the eventual chat-product shape.
20. The UI needed a clearer split between public introduction and authenticated
    workspace.

## Baseline Scores

| Area | Score |
| --- | ---: |
| Public-product first impression | 4.5 / 10 |
| Chinese product language fit | 4.0 / 10 |
| Login entry clarity | 5.0 / 10 |
| Chat-workspace fit | 5.5 / 10 |
| Conversation history design | 4.0 / 10 |
| Video analysis workflow | 7.0 / 10 |
| Diagnostics placement | 6.5 / 10 |
| Mobile adaptation | 6.5 / 10 |
| Overall iOS-level polish | 5.5 / 10 |

Overall baseline: 5.4 / 10.

## Implemented Response In Code

- Added a Chinese product-introduction first page with a single top-right
  `登录` entry.
- Moved the OpenClaw-owned username/password form into a login dialog.
- Added the authenticated Chinese chat workspace shell.
- Added `sessionList` rendering backed by the existing `/sessions` API.
- Added session selection and message refresh backed by existing message APIs.
- Kept the video-link read, model-analysis, upload fallback and result status
  controls inside the logged-in workspace.
- Demoted diagnostics under `验证工具`.
- Demoted sanitized raw JSON under `开发详情：脱敏响应`.
- Preserved automation selectors used by root Chrome acceptance.

## Selectors Preserved

```text
loginAccount
loginPassword
loginButton
authStatus
identityDiagnostics
runPostLoginAcceptance
runSelfTest
runSecurityTest
createSession
sessionId
videoUrl
prompt
readVideoLink
submitJob
pollJob
videoFile
uploadJob
uploadSmoke
output
```

Additional product UI selectors in the current design:

```text
openLogin
landingPage
chatApp
sessionList
nextAction
sendChat
refreshMessages
loginPanel
sessionPanel
videoPanel
conversationPanel
validationTools
```
