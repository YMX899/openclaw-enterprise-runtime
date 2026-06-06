# Ubuntu 22.04 Dify Browser Baseline

Audit time: 2026-06-06 19:15 Asia/Shanghai
Target host: `ubuntu22.04`
Base URL: `http://192.168.206.130:8088`
Mode: Ubuntu 22.04 test-host Dify baseline after Phase 1.5 isolated
OpenClaw validation.

## Server Facts

```text
Dify Nginx container: dify_v1110_a8be-nginx-1
Nginx port mapping: 0.0.0.0:8088 -> 80/tcp
Dify Web container: dify_v1110_a8be-web-1
Dify API container: dify_v1110_a8be-api-1
Dify version: 1.11.2
Dify network: dify_v1110_a8be_default
```

All checks below avoided reading cookies, authorization headers, CSRF tokens,
full `.env` files, database connection strings, Redis credentials, private
keys, and model API keys.

## Server-Side HTTP Baseline

From `ubuntu22.04` against `127.0.0.1:8088`:

```text
GET / -> 307 redirect to /apps
GET /signin -> 200, body bytes 23226
GET /apps -> 200, body bytes 50506
GET /console/api/account/profile -> 401, body bytes 78
```

Recent Dify log error scan:

```text
dify_v1110_a8be-nginx-1: no recent error/exception/traceback/5xx summary
dify_v1110_a8be-web-1: no recent error/exception/traceback/5xx summary
dify_v1110_a8be-api-1: no recent error/exception/traceback/5xx summary
```

## Real Chrome Browser Baseline

Route:

```text
http://192.168.206.130:8088/signin
```

Observed:

```text
finalUrl: http://192.168.206.130:8088/signin
title: Dify
visible page: Dify login page
browser console errors: none captured
```

Visible DOM markers:

```text
简体中文
登录 Dify
欢迎
邮箱
密码
忘记密码？
登录
设置管理员账户
© 2026 LangGenius, Inc. All rights reserved.
```

Route:

```text
http://192.168.206.130:8088/apps
```

Observed:

```text
finalUrl: http://192.168.206.130:8088/signin
title: Dify
visible page: Dify login page
browser console errors: none captured
```

Interpretation:

```text
Unauthenticated /apps redirects to /signin in the real browser, which is acceptable for this Dify policy.
```

Route:

```text
http://192.168.206.130:8088/console/api/account/profile
```

Observed from direct Chrome navigation:

```text
net::ERR_BLOCKED_BY_CLIENT
```

Interpretation:

```text
The Chrome automation layer blocks direct API-path navigation. This is not treated as a Dify failure.
Server-side HTTP baseline confirms the unauthenticated profile endpoint returns 401, which is expected.
```

## Post-Phase 1.5 Cleanup

After the OpenClaw Phase 1.5 validation run:

```text
OpenClaw sidecar containers: none remaining
Test listeners on 18181/18789/5432: none remaining
Dify containers: still running
OpenClaw compose down --remove-orphans --volumes: PASS
```

## Status

```text
Ubuntu 22.04 unauthenticated real-browser Dify baseline: PASS
Ubuntu 22.04 server-side Dify HTTP/API baseline: PASS
Authenticated Dify app conversation baseline: PASS
```

## Authenticated Chrome Baseline

Audit time: 2026-06-06 19:42-19:52 Asia/Shanghai

Test account and workspace:

```text
test account: openclaw-baseline+ubuntu22@local.test
workspace: OpenClaw Ubuntu22 Baseline
purpose: Ubuntu 22.04 Dify authenticated browser baseline only
credential storage: /home/xiejuyang/.openclaw-phase1.5-secrets/dify_baseline_login.json
credential file mode: 600
```

The test password was generated on the Ubuntu test host and was not printed,
committed, copied into logs, or written into this document. Browser testing did
not read or record cookies, Authorization headers, CSRF tokens, local storage,
session storage, full request headers, `.env` files, database connection
strings, Redis credentials, private keys, or model API keys.

Temporary secret copies staged inside the Dify API container were removed:

```text
TEMP_SECRET_RESIDUE_CLEARED
```

Created baseline app:

```text
app name: OpenClaw Baseline Fixed Reply
app id: 06c9e25c-f763-4fa0-b49b-cd90c1fc1725
mode: advanced-chat
workflow: Start -> Answer
model dependency: none
published: PASS
```

The app was intentionally created as a no-model Chatflow using an Answer node,
so the baseline proves Dify login, workspace routing, app opening, workflow
publishing, webapp runtime, message submission, response rendering, refresh and
logout without depending on an external LLM provider.

Authenticated browser observations:

```text
GET /apps after login:
  finalUrl: http://192.168.206.130:8088/apps
  title: 工作室 - Dify
  workspace visible: OpenClaw Ubuntu22 Baseline
  app visible: OpenClaw Baseline Fixed Reply
  browser console errors: none captured

Open app:
  finalUrl: http://192.168.206.130:8088/app/06c9e25c-f763-4fa0-b49b-cd90c1fc1725/workflow
  title: OpenClaw Baseline Fixed Reply - Dify
  page visible: workflow orchestration page
  publish state: 已发布
  browser console errors: none captured

Run webapp:
  finalUrl: http://192.168.206.130:8088/chat/WUJNxt0ATrXul8rm
  title: OpenClaw Baseline Fixed Reply - Dify
  input visible: 和 OpenClaw Baseline Fixed Reply 聊天
  browser console errors: none captured

Message flow:
  user message: ping baseline 0606
  expected reply: OpenClaw baseline reply ping baseline 0606
  reply visible: PASS
  browser console errors: none captured

Refresh:
  route: http://192.168.206.130:8088/chat/WUJNxt0ATrXul8rm
  prior user message visible after refresh: PASS
  prior answer visible after refresh: PASS
  browser console errors: none captured

Return to /apps:
  route: http://192.168.206.130:8088/apps
  app entry visible: PASS
  browser console errors: none captured

Logout:
  menu item: 登出
  after logout /apps finalUrl: http://192.168.206.130:8088/signin
  signin page visible: PASS
  browser console errors: none captured
```

Recent Dify container status after the authenticated baseline:

```text
dify_v1110_a8be-nginx-1: Up 7 hours, 0.0.0.0:8088->80/tcp
dify_v1110_a8be-worker-1: Up 7 hours
dify_v1110_a8be-api-1: Up 7 hours
dify_v1110_a8be-worker_beat-1: Up 7 hours
dify_v1110_a8be-plugin_daemon-1: Up 7 hours
dify_v1110_a8be-db_postgres-1: Up 7 hours (healthy)
dify_v1110_a8be-redis-1: Up 7 hours (healthy)
dify_v1110_a8be-web-1: Up 7 hours
dify_v1110_a8be-sandbox-1: Up 7 hours (healthy)
dify_v1110_a8be-weaviate-1: Up 7 hours
dify_v1110_a8be-ssrf_proxy-1: Up 7 hours
```

Recent log summary after the authenticated baseline:

```text
dify_v1110_a8be-web-1: 0 recent error/exception/traceback/5xx matches
dify_v1110_a8be-api-1: 0 recent error/exception/traceback/5xx matches
dify_v1110_a8be-nginx-1: 0 confirmed recent 5xx; grep produced false positives from static CSS/API 200 access lines
```

Post-test sidecar isolation:

```text
OpenClaw sidecar containers: none remaining
Test listeners on 18181/18789/5432: none remaining
```

Gate markers for Ubuntu 22.04 test host:

```text
ubuntu22_authenticated_baseline: PASS
authenticated_baseline: PASS
existing app message: PASS
streaming reply: PASS
refresh: PASS
history: PASS
logout: PASS
profile 401: PASS
new 5xx: NONE
```

This is Ubuntu 22.04 test-host evidence. It does not replace the separate
production/root public baseline for `https://ai001.huahuoai.com`, which still
requires its own authenticated real-browser run before any production public
OpenClaw route exposure.
