# Production Root Missing Gates

Date: 2026-06-06 Asia/Shanghai

Status: root deployment is still NO_GO. This file records what is still missing
after the Ubuntu 22.04 test phase passed. It is intentionally versioned so the
system can return to the previous state by checking out the tagged commit before
any future production deploy bundle is built.

Scope clarification on 2026-06-07: the user-facing Dify web path for this
integration is the Huahuo/OpenClaw page on `https://www.huahuoai.com`, not the
legacy `https://ai001.huahuoai.com/apps` operator console. The production
readiness gate named `authenticated_dify_baseline` is kept for compatibility
with older preflight code, but it is now satisfied by the OpenClaw standalone
login browser evidence. The legacy ai001 console login is no longer a blocking
requirement for this project.

Scheme clarification on 2026-06-07: the Douyin path now uses video link-read
mode. Douyin account login, browser storage state, and
`REAL_SAMPLE_EVIDENCE.json` are no longer production readiness blockers.

No cookies, Authorization headers, CSRF values, browser storage, password
values, private key contents, model API key contents, `.env` contents, database
connection strings, Redis passwords or full request headers were read or
recorded for this inventory.

## Current Passed Items

- Ubuntu 22.04 phase audit: PASS.
- Isolated Linux Docker Phase 1.5 proof: PASS.
- Ubuntu 22.04 authenticated Dify baseline: PASS.
- OpenClaw standalone login on Huahuo user web: PASS.
- OpenClaw version under test: `2026.3.13`.
- OpenClaw security triage: allowed by operator-approved exception.
- `douyin_chong` artifact manifest: verified.
- Video link-read mode: adopted.
- `REAL_SAMPLE_EVIDENCE.json`: optional diagnostic evidence, not required for
  the adopted link-read production scheme.
- Ubuntu 22.04 `openclaw_bridge_device_key.pem`: present, mode `600`, contents
  not read.
- Ubuntu 22.04 `douyin_chong.env`: present, mode `600`, contents not read.
- Ubuntu 22.04 OpenClaw gateway token file: present, mode `600`, contents not
  read.
- Production root OpenClaw public route: absent.
- Production root Dify internal unauthenticated checks: `/signin` 200, `/apps`
  200, `/console/api/account/profile` 401.

## Blocking Item

No hard blocker remains from Dify web login or Douyin sample evidence after the
2026-06-07 scope and scheme clarifications. The current production readiness
audit should be used for the live gate state.

```text
remaining production readiness gate: none expected from login/sample scope
```

Current evidence:

```text
OpenClaw standalone login evidence: PASS
Huahuo/OpenClaw post-login browser acceptance: PASS
REAL_SAMPLE_EVIDENCE.json: missing
latest real sample attempt: Ark model authentication returned HTTP 401
video link-read mode: ADOPTED
remaining production readiness gate from this document: NONE
```

This means `REAL_SAMPLE_EVIDENCE.json` is retained only as optional diagnostic
history. The OpenClaw browser login scope and the Douyin sample-evidence scope
are no longer blocking.

## Retired Legacy Browser Baseline

The old ai001 console browser baseline below is retained as historical context
only. It is not part of the current blocking checklist because users now log in
to the OpenClaw page itself.

The next operator action is to open Chrome manually, sign in to:

```text
https://ai001.huahuoai.com/apps
```

Then keep that tab open and let Codex continue from the already logged-in tab.
Codex must only read visible page state, route URLs, page titles, screenshots
where needed, and console/network error summaries. Codex must not read cookies,
local storage, session storage, request headers, CSRF values, Authorization
tokens or passwords.

The production baseline can pass only after the following are verified through
the real public browser path:

- Logged-in `/apps` opens successfully.
- At least one existing Dify app opens successfully.
- One existing app message can be sent.
- A normal or streaming reply is visible.
- Page refresh preserves expected state.
- History or existing conversation entry opens normally.
- Logout works normally.
- `/console/api/account/profile` is still 401 when not logged in.
- No new 5xx appears in the tested public route flow.
- `docker-api-1`, `docker-web-1` and `docker-nginx-1` do not show new relevant
  errors caused by the test.

If there is no safe existing production app to test, one more explicit operator
decision is needed: either name a production app that Codex may use for the
baseline, or approve creation of a temporary no-model baseline app. Codex should
not create or modify production Dify apps without that explicit approval.

## Root Health Note

Read-only root refresh at `2026-06-06T20:11:37+08:00` showed:

```text
http://127.0.0.1:8081/ -> 307
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
docker-nginx-1 recent error/exception/traceback/5xx matches: 0
docker-web-1 recent error/exception/traceback/5xx matches: 0
docker-api-1 recent error/exception/traceback/5xx matches: 1
```

The `docker-api-1` log match count must be reviewed during the final production
baseline. It is not treated as proof that Dify is down, but it should not be
ignored before opening a public OpenClaw route.

## Version And Rollback Control

Current baseline commit before this inventory:

```text
54dd72f phase1-5-root-preflight-deferred-sample-20260606
```

Before any production deploy attempt:

- The worktree must be clean.
- HEAD must have a version tag.
- `scripts/preflight_root_deploy.py --target-host root --fail-on-no-go` must
  return GO.
- The deploy bundle must be created by `scripts/build_root_deploy_bundle.py`,
  not by hand-copying a working directory.
- OpenResty route changes must be isolated and reversible without restarting
  Dify containers.
