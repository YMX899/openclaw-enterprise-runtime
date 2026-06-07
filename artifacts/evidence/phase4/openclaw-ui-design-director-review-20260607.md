# OpenClaw UI Design Director Review - 2026-06-07

Role executed: now I am acting as the visual communication design director of a top-tier software company. I inspected the OpenClaw product purpose, captured screenshots, reviewed the current HTML/CSS/JS surface, scored the UI, and converted the findings into executable improvement requirements. Because the main thread is actively changing `openclaw-video/src/openclaw_video/bridge_app.py`, this worker did not edit authentication logic, video APIs, database code, deployment scripts, or the dirty backend/UI source file.

## Evidence Reviewed

- Product baseline: `D:\DESK\Dify\openclaw-engineering-baseline.md`
- Pragmatic gates: `D:\DESK\Dify\development-pragmatic-gates-20260607.md`
- Go/no-go matrix: `D:\DESK\Dify\go-no-go-gate-matrix.md`
- Current bridge page source, read-only: `D:\DESK\Dify\openclaw-video\src\openclaw_video\bridge_app.py`
- Public acceptance evidence: `D:\DESK\Dify\artifacts\evidence\phase4\openclaw-current-root-chrome-evidence-20260607.json`
- Desktop screenshot: `D:\DESK\Dify\artifacts\evidence\phase4\openclaw-ui-screenshot-public-20260607.png`
- Mobile screenshot: `D:\DESK\Dify\artifacts\evidence\phase4\openclaw-ui-screenshot-public-mobile-20260607.png`

## Product Understanding

OpenClaw Lab is no longer a Dify Web login extension, a temporary testing harness, or a Douyin account login flow. It is the browser-facing product surface for OpenClaw's own account/password login, session creation, short-video link reading, optional upload, asynchronous analysis, chat/result review, and post-login/security acceptance checks.

The primary user goal is: log in with an OpenClaw-owned account, create or resume a task workspace, submit a short-video link or upload a file, monitor analysis progress, and review a structured result. The secondary operator goal is: run identity diagnostics, security negatives, upload smoke, and post-login acceptance without exposing tokens, cookies, headers, or private Gateway details.

That dual goal is currently visible in the UI, but the balance is off: the interface reads more like a QA console than a finished short-video analysis workbench. The visual system is disciplined enough to be usable, but not yet at iOS-level product polish.

## Screenshot-Based Observations

Desktop view:

- The page loads reliably and has a coherent two-column workbench.
- The left rail contains the actual task flow, but engineering controls interrupt the primary path.
- The right JSON/status panel dominates the first screen despite being support-oriented, not the user's main value.
- The visual language is mostly clean SaaS tooling, but lacks a refined product identity, motion/state clarity, and result-oriented hierarchy.

Mobile view:

- No obvious text overlap was observed at 390px width.
- Buttons stack safely, but the screen becomes long and operationally heavy.
- Status chips and login controls fit, but every action receives nearly equal weight, making the next step less obvious.
- The output/result area falls far below the primary form; this is acceptable for mobile, but needs a sticky compact progress summary after job submission.

## Current UI Score

Scores are for the current visible implementation, not for the proposed design direction.

| Dimension | Score | Reason |
| --- | ---: | --- |
| Product clarity | 7/10 | The page says what it is, but does not clearly stage the user journey from login to result. |
| Visual hierarchy | 7/10 | Panels are orderly, but diagnostics and task actions compete for attention. |
| Interaction design | 7/10 | Controls are reachable and responsive, but primary/secondary/destructive/operator actions are not separated enough. |
| iOS-level polish | 6/10 | Spacing, radii, shadows, typography and state language are competent, not premium. |
| Mobile ergonomics | 7/10 | Responsive layout works, but action density is high and progressive disclosure is missing. |
| Result readability | 5/10 | Raw JSON is useful for support, but it should not be the main result presentation. |
| Trust and safety communication | 8/10 | Auth status, private session, and sanitized output are present, though too technical. |
| Brand/product identity | 6/10 | "OC" mark and title are clear but generic; no distinctive OpenClaw product feel yet. |
| Accessibility and resilience | 7/10 | Labels and focus styles exist; more semantic grouping and disabled/loading states are needed. |
| Overall | 70/100 | Usable Phase 4 workbench, not yet a release-quality product UI. |

Director decision: current UI does not receive a full score. Because this worker must not overwrite the active `bridge_app.py` edits, the executable outcome is a gated design-change list for the main thread to merge. After those changes are applied and screenshot-tested, the target design can reach 100/100 for the current product scope.

## Twenty UI And Visual Design Problems

1. The first screen does not make the primary user promise obvious enough: "analyze a short video and get an actionable result" should outrank acceptance/testing language.
2. Login, session creation, video submission, upload, diagnostics, security tests, and output all appear as peer features; the user path needs a clear step model.
3. The right-side "Job Result & Status" panel is visually heavier than the actual submission workflow because the dark JSON block has high contrast and large area.
4. Raw JSON is the default output presentation, which is appropriate for evidence but not for a product user reviewing analysis.
5. "Self Test", "Security Test", and "Post-Login Acceptance" are operator controls placed too close to the user flow.
6. "Refresh Login" and "Identity Check" are technical labels; they should be recast as status actions or moved into a compact diagnostics drawer.
7. Button hierarchy is too flat: multiple secondary buttons look almost as important as the primary action in each panel.
8. There is no explicit progress stepper for login -> session -> source -> analysis -> result.
9. Session ID is exposed as an editable primary field; useful for diagnostics, but not a friendly product primitive.
10. The conversation area is too small and static to feel like a real chat/result workspace.
11. Upload and link analysis share a panel but do not use a segmented source selector, so the user must infer which fields apply.
12. The "Read Link" affordance is useful but missing from the observed public desktop screenshot near the submit action, suggesting deployed and local source may be out of sync or cropped; it should be positioned consistently.
13. The status chips use text like "Refreshing" and "Checking" without a time/progress expectation.
14. There is no empty-state illustration, preview, or result skeleton to make the workbench feel alive before a job exists.
15. The brand mark is functional but generic; it does not communicate short-video intelligence, analysis, or OpenClaw's own product identity.
16. The color system leans heavily on blue, slate, and pale panels; it needs a more refined accent palette without becoming decorative.
17. The panel shadows and borders are serviceable but lack depth discipline: every panel has similar weight, so the eye has no resting hierarchy.
18. Mobile layout stacks safely but requires too much scrolling before the user sees what result or progress will look like.
19. The current UI has no compact "last job" card with status, source, elapsed time, and next action.
20. Error and success states are structurally present, but they are not yet written in product language that helps a non-engineer recover.

## Modification Principles For A Full-Score UI

1. Make the first viewport a workbench, not a test harness.
2. Preserve every required automation selector and API behavior listed in the baseline.
3. Keep operator checks available, but move them into a collapsible "Diagnostics" area below the main workflow or behind a secondary toolbar.
4. Use progressive disclosure: login first, then session/source, then progress/result.
5. Replace raw JSON as the default result view with a readable summary, while keeping JSON in a "Raw" tab.
6. Use a clear stepper or status rail for `Login`, `Session`, `Source`, `Analysis`, `Result`.
7. Make "Submit Job" the obvious primary command only after a session and video source are present.
8. Treat "Read Link" as a preflight action beside the URL field, not as a competing submit command.
9. Make upload and URL modes mutually clear with a segmented control.
10. Keep the visual system restrained: neutral surfaces, one primary blue, one analysis accent, clear semantic colors, no decorative blobs.
11. On desktop, keep the result/progress panel sticky, but reduce raw JSON dominance.
12. On mobile, introduce a compact sticky status summary after login/job creation.
13. Improve button copy: use user-facing verbs for the main flow and operator-facing verbs only inside diagnostics.
14. Add strong empty states: "No source yet", "Ready to analyze", "Result will appear here".
15. Improve microcopy for rejected URLs and job failures so the user knows whether to edit the link, retry, or contact support.
16. Apply consistent density: panels should use a tighter 8px radius, but more intentional section spacing and headers.
17. Add subtle icons via an icon library if the page later moves into a bundled frontend; for the current no-build HTML, text-only is acceptable.
18. Keep screenshot tests at desktop and mobile widths after each visual change.
19. Ensure no token, cookie, header, secret, or raw environment detail appears in the page or evidence.
20. Separate user result presentation from acceptance evidence so the product can serve both creators and operators.

## Concrete Main-Thread Change List

These changes can be merged after the main thread finishes its bridge/video-link work. They are intentionally scoped to UI HTML/CSS/JS and must preserve existing element IDs.

### 1. Reframe The Header

Current:

- Eyebrow: "Short video analysis workbench"
- H1: "OpenClaw Lab"
- Status chips on the right.

Change:

- Keep H1 as `OpenClaw Lab`.
- Add one concise product subtitle under the title: "Analyze short-video links and uploads with an OpenClaw private session."
- Keep status chips, but use `Ready`, `Signed out` / `Signed in`, `Working`, `Result ready`.
- Add a compact step indicator below the header:
  `Login -> Session -> Source -> Analyze -> Result`

### 2. Convert Workflow Panels Into A Step-Based Left Column

Keep the current left-column structure but visually number sections:

- Step 1: Sign in
- Step 2: Create analysis session
- Step 3: Choose source
- Step 4: Submit and monitor

The labels can remain English for consistency with current source, but the visual grouping should make the sequence obvious without reading paragraphs.

### 3. Move Diagnostics Out Of The Primary Action Row

Move these controls into a collapsible diagnostics panel:

- `identityDiagnostics`
- `runSelfTest`
- `runSecurityTest`
- `runPostLoginAcceptance`

Keep their IDs unchanged. Recommended label for collapsed trigger: `Diagnostics`.

Primary flow should show:

- Login panel: `Login`; secondary `Logout`
- Session panel: `Create Session`
- Source panel: URL mode with `Read Link` and `Submit Job`; Upload mode with `Upload Job`
- Result panel: `Poll Job` only when a job exists

### 4. Use A Source Mode Control

Add a small segmented control in the Video Job section:

- `Link`
- `Upload`

Do not remove existing `videoUrl`, `videoFile`, `submitJob`, `uploadJob`, or `uploadSmoke` IDs. Instead, hide/show groups with CSS/JS. The default should be `Link`.

### 5. Replace Raw JSON Dominance With Result Tabs

Keep `output` as the raw JSON `<pre>` for automation and support. Add a visual summary above it:

- Status
- Source
- Job ID
- Created/finished time
- Error recovery text or result summary

Then add tabs:

- `Summary`
- `Conversation`
- `Raw`

If a full tab implementation is too much for this phase, at minimum collapse raw JSON under a `details` element titled `Raw response`.

### 6. Improve Current CSS Without Changing Architecture

Safe CSS direction for the current inline page:

```css
:root {
  --page: #f6f7f9;
  --surface: #ffffff;
  --surface-raised: #fbfcfe;
  --border: #d9e0ea;
  --text: #0f172a;
  --muted: #64748b;
  --primary: #2563eb;
  --analysis: #0f766e;
}

.panel {
  box-shadow: 0 1px 2px rgba(15, 23, 42, .04), 0 18px 40px rgba(15, 23, 42, .06);
}

.operator-actions {
  border-top: 1px solid var(--faint);
  margin-top: 14px;
  padding-top: 12px;
}

.result-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  background: linear-gradient(180deg, #ffffff, #f8fafc);
}

.raw-output-collapsed pre {
  max-height: 260px;
}
```

The exact class names can differ, but the underlying move is important: support output should not visually overpower the task surface.

### 7. Add State-Specific Empty And Recovery Copy

Recommended product-language states:

- Signed out: "Sign in to start a private OpenClaw analysis session."
- No session: "Create a session before sending a link or upload."
- No source: "Paste a Douyin video link or upload a local MP4/MOV/WebM."
- URL rejected: "This link cannot be read by OpenClaw. Use a supported public video link and try again."
- Job queued: "Analysis is queued. You can keep this page open and poll for updates."
- Job succeeded: "Analysis result is ready."
- Job failed: "OpenClaw could not complete this analysis. Review the reason below."

### 8. Add Screenshot Acceptance Gates

After UI changes, capture and inspect:

- Desktop: 1440x1100 at `https://www.huahuoai.com/ai/openclaw-lab/`
- Mobile: 390x1200 at the same URL
- Logged-out state
- Logged-in state without recording account/password/cookies
- Job pending/succeeded/failure states, using sanitized evidence only

Pass criteria:

- No overlapping text or controls.
- Primary action is visually obvious in each step.
- Operator diagnostics are accessible but not dominant.
- Raw JSON is available but not the default visual focus.
- Mobile first screen shows brand, status, and login without cramped controls.
- No secrets, cookies, authorization headers, local storage values, or raw URLs are recorded.

## Target Full-Score Design Definition

The UI can be considered 100/100 for this phase when:

- A new user can infer the workflow in under five seconds.
- The main task path is visually stronger than diagnostics.
- Result review has a human-readable summary before raw JSON.
- Mobile is not merely stacked desktop controls; it has a compact state summary.
- The design uses a disciplined, modern product-tool aesthetic with iOS-level spacing, focus states, readable typography, clear hierarchy, and no visual clutter.
- Automation selectors and API behavior remain unchanged.
- Desktop and mobile screenshots pass visual review.

## Current Exit Decision

This worker cannot honestly mark the current UI as full score. It is acceptable for Phase 4 functional acceptance, but not yet at the requested visual-design bar. Since `bridge_app.py` is currently dirty and owned by the main thread, the safe exit is to deliver this review as the design director's required change list rather than editing the active bridge source.

Recommended next action for the main thread: after completing the video-link bridge changes, apply the UI-only changes above in `LAB_PAGE_HTML`, run the browser screenshot gates, then request a visual re-review against the 100/100 definition.
