# Production Root Missing Gates

Date: 2026-06-06 Asia/Shanghai

Status: root deployment is still NO_GO. This file records what is still missing
after the Ubuntu 22.04 test phase passed. It is intentionally versioned so the
system can return to the previous state by checking out the tagged commit before
any future production deploy bundle is built.

No cookies, Authorization headers, CSRF values, browser storage, password
values, private key contents, model API key contents, `.env` contents, database
connection strings, Redis passwords or full request headers were read or
recorded for this inventory.

## Current Passed Items

- Ubuntu 22.04 phase audit: PASS.
- Isolated Linux Docker Phase 1.5 proof: PASS.
- Ubuntu 22.04 authenticated Dify baseline: PASS.
- OpenClaw version under test: `2026.3.13`.
- OpenClaw security triage: allowed by operator-approved exception.
- `douyin_chong` artifact manifest: verified.
- `REAL_SAMPLE_EVIDENCE.json`: explicitly deferred for the current Ubuntu 22.04
  phase by operator instruction. Final production can still require it by
  running without `ALLOW_DOUYIN_SAMPLE_DEFERRED=1`.
- Ubuntu 22.04 `openclaw_bridge_device_key.pem`: present, mode `600`, contents
  not read.
- Ubuntu 22.04 `douyin_chong.env`: present, mode `600`, contents not read.
- Ubuntu 22.04 OpenClaw gateway token file: present, mode `600`, contents not
  read.
- Production root OpenClaw public route: absent.
- Production root Dify internal unauthenticated checks: `/signin` 200, `/apps`
  200, `/console/api/account/profile` 401.

## Blocking Item

The remaining hard blocker is:

```text
authenticated_dify_baseline
```

Current evidence:

```text
Chrome open tabs matching ai001.huahuoai.com or Dify: 0
prior direct Chrome navigation: net::ERR_BLOCKED_BY_CLIENT
root deploy preflight with ALLOW_DOUYIN_SAMPLE_DEFERRED=1: NO_GO
remaining preflight gate: authenticated_dify_baseline
```

This means the system still needs a real logged-in production Dify browser
baseline before any root deployment or public `/openclaw-lab/` route work.

## Required Production Browser Baseline

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
