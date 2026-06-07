# OpenClaw UI/Product Visual Review - 2026-06-07

Role prompt used for this review:

> "现在你是顶级软件公司的视觉传达设计总监，你必须从你的角度，调用视觉能力自行截图，然后优化 UI 设计，直到整个设计初步通过你的审核。然后你作为 UI 和产品专家，理解整个工程的作用，从资深业内人士的角度提出 20 个 UI 设计和视觉设计的问题。然后用现在的 UI 设计进行打分。根据打分和判断结果进行修改，只有都满分才能退出。（视觉设计要求至少在 iOS 级别的审美以上）"

## Scope And Evidence

Review target: OpenClaw Lab page, including standalone login, video link
submission, upload fallback, conversation/prompt area, result output, and
diagnostic/acceptance controls.

Runtime target inspected: `https://www.huahuoai.com/ai/openclaw-lab/`

Evidence captured:

- Desktop viewport screenshot:
  `artifacts/evidence/phase4/openclaw-ui-design-agent-review-desktop-20260607.png`
- Existing mobile screenshot used as mobile evidence:
  `artifacts/evidence/phase4/openclaw-ui-screenshot-public-mobile-20260607.png`
- DOM/visual metrics collected from Chrome: page title, headings, inputs,
  buttons, primary container metrics, color/radius samples, and overflow scan.

Screenshot limitation:

- A full-page Chrome screenshot attempt timed out at the extension capture
  layer.
- A desktop viewport screenshot was captured successfully.
- Mobile assessment used the existing mobile screenshot plus current DOM and
  spacing metrics.

Safety constraints honored:

- No account, password, cookie, header, token, API key, database URL, raw video
  link, direct media URL, or model body text is recorded in this report.
- No Dify container was restarted.
- No OpenClaw functional source file was modified by the design review agent.

## Product Understanding

OpenClaw Lab is becoming the standalone operating surface for short-video
analysis. It no longer depends on logging into the Dify web UI or on
browser-cookie based Douyin login. The user logs into OpenClaw, creates a
private analysis session, submits an allowlisted video link or compact upload,
and receives sanitized job state plus analysis output. The page also contains
diagnostic and acceptance controls because the project is still in
deployment-hardening mode.

From a product point of view, this page is not a marketing site. It should
behave like a professional analysis workbench: calm, trustworthy, fast to scan,
safe by default, and precise enough for repeated operator use. The most
important interface promise is: "I know where I am, what credentials/session I
am using, what video/task is being analyzed, what the system is doing now, and
what result or failure requires action."

The inspected implementation proved the workflow, but the visual language still
read as an internal engineering test console. It was acceptable for
verification, not yet acceptable as the primary product UI.

## Twenty UI And Visual Design Issues

1. The page led with implementation sections instead of a clear user task flow.
2. Diagnostic controls competed with primary product actions.
3. The result panel had too much visual weight before a job existed.
4. The conversation area looked like a note box rather than a dialogue surface.
5. Status pills were too generic for auth, session, worker, and job state.
6. Primary action hierarchy was inconsistent across login/session/job/upload.
7. Secondary buttons were visually heavy, especially on mobile.
8. Login fields stayed prominent even after authentication.
9. The video URL input lacked an inline validation state.
10. `Read Link` and `Submit Job` were not differentiated enough.
11. Upload was visually welded into the link flow.
12. The dark JSON block was not scannable for normal users.
13. Card headings were visually too similar.
14. The aesthetic read as a narrow internal tool rather than a polished app.
15. Brand identity was minimal and under-expressive.
16. Mobile layout was usable but too vertically long.
17. File input used default browser styling.
18. Helper copy was accurate but engineering-centered.
19. Error and empty states were not visually differentiated enough.
20. Acceptance and support workflows were visible in the main lane.

## Scorecard

Scoring standard: 10 means iOS-level product polish and high-confidence
repeated-use ergonomics. Current score reflects the inspected UI before the
main-thread productization pass, not backend functionality.

| Category | Score | Rationale |
| --- | ---: | --- |
| Product clarity | 7/10 | Purpose was understandable, but task flow was expressed as engineering blocks. |
| Information architecture | 6/10 | Login, session, job, upload, diagnostics, and results were all visible at once. |
| Visual hierarchy | 6/10 | Primary and secondary actions competed; empty JSON dominated the layout. |
| Interaction ergonomics | 6/10 | Workflow was operable but not yet guided. |
| Typography | 7/10 | Clean and legible, but helper copy lacked premium hierarchy. |
| Layout and spacing | 7/10 | Desktop layout was stable and mobile stacked cleanly. |
| Color and depth | 6/10 | Functional blue/neutral palette was usable but not sophisticated. |
| Component quality | 6/10 | Buttons and inputs were consistent; result and conversation needed redesign. |
| Trust and safety presentation | 7/10 | Auth and sanitization existed but safety state needed clearer presentation. |
| iOS-level aesthetic | 5/10 | Clean, but not yet at the polished native-app feeling requested. |

Total: 63/100.

Current verdict: not approved as an iOS-level product UI. Approved only as a
functional engineering workbench baseline.

## Main-Thread Changes Applied From This Review

- Added a guided five-step workflow: Login, Session, Source, Analyze, Result.
- Moved diagnostics and acceptance controls into a collapsed drawer.
- Reworked the result area into summary metric cards plus an on-demand raw JSON
  details panel.
- Split video source controls into Link and Upload tabs.
- Renamed primary actions toward operator intent: `Check Link`,
  `Analyze Video`, `Refresh Status`, and `Analyze Upload`.
- Kept existing automation selectors stable, including `readVideoLink`,
  `submitJob`, `pollJob`, `uploadJob`, `uploadSmoke`, and `output`.
- Added flow-state updates for login, session creation, source selection,
  submission, polling, and result readiness.
- Added basic ARIA tab metadata for the source selector.
- Updated OpenClaw engineering memory docs with the root-first UI verification
  policy requested by the user.

## Remaining Visual Approval Criteria

The next root-side visual review should verify:

- The first viewport communicates the analysis workflow without reading every
  helper line.
- Diagnostics remain secondary and do not compete with analysis actions.
- Result output defaults to product-readable states instead of empty/raw JSON.
- Mobile layout avoids horizontal overflow and does not overlap text or controls.
- The page feels like a polished analysis product rather than a deployment test
  console.
