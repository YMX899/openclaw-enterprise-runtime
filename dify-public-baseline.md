# Dify Public Baseline

Audit time: 2026-06-06 01:30 Asia/Shanghai  
Target public host: `https://ai001.huahuoai.com`  
Mode: Phase 0 real browser and non-mutating HTTP checks.

## Summary

The Dify sign-in page is reachable from the local Chrome browser. Unauthenticated `/apps` redirects to `/signin`, which is expected. A direct browser navigation to `/console/api/account/profile` was blocked by the browser client as `net::ERR_BLOCKED_BY_CLIENT`; internal Dify API checks still show unauthenticated profile requests return `401`, which is expected.

Server-side `curl` from the root server to the same public HTTPS host returned `403 Forbidden` from OpenResty, while the user's Chrome browser could load the sign-in page. This confirms that real browser testing must be part of every future acceptance and rollback run; server-side curl alone is not a reliable substitute for public browser behavior.

## Real Chrome Browser Baseline

Browser route:

```text
https://ai001.huahuoai.com/signin
```

Observed:

```text
title: Dify
url: https://ai001.huahuoai.com/signin
visible page: Dify login page
browser console errors/warnings: none captured
```

Visible DOM markers:

```text
Dify logo
登录 Dify
👋 欢迎！请登录以开始使用。
邮箱 input
密码 input
忘记密码？
登录 button disabled before credentials
设置管理员账户 link
© 2026 LangGenius, Inc. All rights reserved.
```

Browser route:

```text
https://ai001.huahuoai.com/apps
```

Observed:

```text
finalUrl: https://ai001.huahuoai.com/signin
title: Dify
visible page: Dify login page
```

Interpretation:

- Without an authenticated Dify session, `/apps` redirects to `/signin`.
- This matches expected unauthenticated behavior and should be used as the pre-login baseline.

Browser route:

```text
https://ai001.huahuoai.com/console/api/account/profile
```

Observed from direct tab navigation:

```text
net::ERR_BLOCKED_BY_CLIENT
```

Interpretation:

- The browser automation layer blocked direct navigation to the API route.
- Do not use this browser navigation failure as a Dify failure signal.
- Internal API checks still confirm profile returns `401` without login.

Screenshot note:

- A screenshot capture attempt timed out at the browser automation layer.
- DOM and title/URL checks succeeded.
- Future acceptance runs should save screenshots using a more stable browser capture path or manual screenshot if the automation capture remains slow.

## Internal Dify Nginx Baseline

From the root server against internal Dify Nginx:

```text
http://127.0.0.1:8081
  -> 307 Temporary Redirect
  -> location: /apps

http://127.0.0.1:8081/apps
  -> 200 OK
  -> Content-Type: text/html; charset=utf-8
  -> X-Powered-By: Next.js

http://127.0.0.1:8081/signin
  -> 200 OK
  -> Content-Type: text/html; charset=utf-8
  -> X-Powered-By: Next.js

http://127.0.0.1:8081/console/api/account/profile
  -> 401 UNAUTHORIZED
  -> message: Invalid Authorization token
  -> X-Version: 1.11.2
  -> X-Env: PRODUCTION
```

From inside `docker-api-1`:

```text
http://127.0.0.1:5001/console/api/account/profile
  -> 401 UNAUTHORIZED
  -> message: Invalid Authorization token
  -> X-Version: 1.11.2
  -> X-Env: PRODUCTION
```

Interpretation:

- Dify internal web and API routing are functional for unauthenticated baseline checks.
- `401` for profile without login is correct.

## Public Host Curl Baseline from Server

From the root server:

```text
https://ai001.huahuoai.com/signin
  -> 403 Forbidden
  -> Server: openresty

https://ai001.huahuoai.com/apps
  -> 403 Forbidden
  -> Server: openresty

https://ai001.huahuoai.com/console/api/account/profile
  -> 403 Forbidden
  -> Server: openresty

https://ai001.huahuoai.com/api
  -> 403 Forbidden
  -> Server: openresty

https://ai001.huahuoai.com/v1
  -> 403 Forbidden
  -> Server: openresty
```

Interpretation:

- Public HTTPS checks from the server itself do not match real Chrome browser behavior.
- This may be due to OpenResty request filtering, source IP, missing browser headers, or other access controls.
- Future acceptance must use real browser checks for public UX.

## Authenticated Baseline Status

Authenticated baseline was not completed because no Dify login credentials were provided and no request was made to submit credentials.

## Authenticated Baseline Retry 2026-06-06

Route tested with the user's real Chrome browser:

```text
https://ai001.huahuoai.com/apps
```

Observed:

```text
finalUrl: https://ai001.huahuoai.com/signin
title: Dify
visible page: Dify login page
visible inputs: email and password
```

Interpretation:

- The current Chrome profile did not have an authenticated Dify session for
  `https://ai001.huahuoai.com`.
- No credentials, cookies, tokens, CSRF values or full request headers were
  read or recorded.
- Existing-app open/message-flow testing is still incomplete and remains a
  required gate before any future public OpenClaw route exposure.

Required before any future OpenClaw route is exposed:

```text
1. Log in to Dify in a real browser.
2. Open /apps.
3. Open at least one existing app.
4. Send a normal existing app message.
5. Confirm reply behavior.
6. Refresh the page.
7. Open existing history or app entry.
8. Sign out.
9. Record screenshots and error-log summaries without Cookie/Token/request-header capture.
```

## Go / No-Go

```text
Unauthenticated real browser Dify baseline: PASS
Internal Dify Nginx/API unauthenticated baseline: PASS
Server-side public curl baseline: NOT REPRESENTATIVE, returns 403
Authenticated Dify app baseline: BLOCKED, credentials/session not provided
```

Future OpenClaw public route work must not proceed past Phase 2 until authenticated real-browser Dify baseline is complete.

## Internal Baseline Refresh 2026-06-06 10:36 Asia/Shanghai

Mode: read-only checks from the root server and inside `docker-api-1`; no
cookies, tokens, CSRF values, credentials or full headers were read.

Server-local internal Dify Nginx:

```text
http://127.0.0.1:8081 -> 200 final http://127.0.0.1:8081/apps
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
```

Inside `docker-api-1`:

```text
http://127.0.0.1:5001/console/api/account/profile -> 401
```

Interpretation:

- Unauthenticated internal Dify baseline remains healthy.
- `401` for profile without login remains expected.
- Authenticated browser baseline is still incomplete and remains mandatory
  before any future public `/openclaw-lab/` or `/openclaw-api/` route exposure.

## Real Chrome Refresh 2026-06-06

Mode: real Chrome browser through the Codex Chrome extension. No cookies, local
storage, request headers, CSRF values, authorization tokens or passwords were
read.

Route:

```text
https://ai001.huahuoai.com/apps
```

Observed:

```text
finalUrl: https://ai001.huahuoai.com/signin
title: Dify
visible page: Dify login page
visible controls: language selector, email input, password input, login button
console/dev error summary: none captured for the signin page
```

Visible text included:

```text
登录 Dify
欢迎！请登录以开始使用。
邮箱
密码
忘记密码？
登录
```

Direct route:

```text
https://ai001.huahuoai.com/signin
```

Observed:

```text
finalUrl: https://ai001.huahuoai.com/signin
title: Dify
visible controls: email input, password input
```

Direct browser navigation to API route:

```text
https://ai001.huahuoai.com/console/api/account/profile
```

Observed:

```text
browser-side error: net::ERR_BLOCKED_BY_CLIENT
visible browser page text: ai001.huahuoai.com 已被屏蔽 / ERR_BLOCKED_BY_CLIENT
```

Interpretation:

- The current Chrome profile still does not have an authenticated Dify session.
- Public unauthenticated UX remains consistent: `/apps` redirects to `/signin`.
- The API direct-tab browser block is still a browser/client behavior and is not
  used as a Dify server failure signal.
- Authenticated existing-app workflow testing remains incomplete and is still a
  required gate before any public OpenClaw route exposure.

## Real Chrome Refresh 2026-06-06 12:16 Asia/Shanghai

Mode: real Chrome browser through the Codex Chrome extension. No cookies, local
storage, session storage, request headers, CSRF values, Authorization tokens or
passwords were read or recorded.

Route:

```text
https://ai001.huahuoai.com/apps
```

Observed:

```text
finalUrl: https://ai001.huahuoai.com/signin
title: Dify
visible page: Dify login page
console/dev error count: 0
```

Visible text:

```text
简体中文
登录 Dify
欢迎！请登录以开始使用。
邮箱
密码
忘记密码？
登录
使用即代表您同意我们的 使用协议 & 隐私政策
如果您还没有初始化账户，请前往初始化页面 设置管理员账户
© 2026 LangGenius, Inc. All rights reserved.
```

Direct route:

```text
https://ai001.huahuoai.com/signin
```

Observed:

```text
finalUrl: https://ai001.huahuoai.com/signin
title: Dify
visible page: Dify login page
console/dev error count: 0
```

Direct browser navigation to:

```text
https://ai001.huahuoai.com/console/api/account/profile
```

Observed:

```text
net::ERR_BLOCKED_BY_CLIENT
```

Interpretation:

- Current Chrome profile still has no authenticated Dify session for
  `https://ai001.huahuoai.com`.
- `/apps` redirecting to `/signin` is expected unauthenticated behavior.
- The direct API navigation error is from the browser automation layer and is
  not treated as a Dify failure. Server-local internal checks in
  `server-readonly-audit.md` still show unauthenticated profile returns `401`.
- Authenticated existing-app open/message/reply/refresh/history/logout testing
  remains incomplete and continues to block any future public OpenClaw route.

Gate markers:

```text
authenticated_baseline: NO_GO
existing app message: NO_GO
streaming reply: NO_GO
refresh: NO_GO
history: NO_GO
logout: NO_GO
profile 401: PASS
new 5xx: NONE
```

## Real Chrome Attempt 2026-06-06 20:01 Asia/Shanghai

Mode: real Chrome browser through the Codex Chrome extension. No cookies, local
storage, session storage, request headers, CSRF values, Authorization tokens or
passwords were read or recorded.

Routes attempted:

```text
https://ai001.huahuoai.com/apps
https://ai001.huahuoai.com/signin
```

Observed:

```text
browser-side error: net::ERR_BLOCKED_BY_CLIENT
```

Interpretation:

- The current Chrome automation layer blocked direct navigation to the
  production public Dify domain before the page could load.
- This is not treated as proof that production Dify is down.
- Because the page could not be opened in Chrome, authenticated existing-app
  open/message/reply/refresh/history/logout testing is still incomplete.

Root server read-only internal refresh at the same time:

```text
http://127.0.0.1:8081/ -> 200 final http://127.0.0.1:8081/apps
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
```

Dify container status and recent logs:

```text
openresty-prod: Up 10 days
docker-nginx-1: Up 5 months
docker-api-1: Up 5 months
docker-web-1: Up 5 months (unhealthy, historical healthcheck issue)
docker-nginx-1 recent error/exception/traceback/5xx matches: 0
docker-web-1 recent error/exception/traceback/5xx matches: 0
docker-api-1 recent error/exception/traceback/5xx matches: 0
```

Gate markers:

```text
authenticated_baseline: NO_GO
existing app message: NO_GO
streaming reply: NO_GO
refresh: NO_GO
history: NO_GO
logout: NO_GO
profile 401: PASS
new 5xx: NONE
```

## Real Chrome Tab Discovery 2026-06-06 20:10 Asia/Shanghai

Mode: real Chrome browser through the Codex Chrome extension. No cookies, local
storage, session storage, request headers, CSRF values, Authorization tokens or
passwords were read or recorded.

Discovery scope:

```text
open Chrome tabs with URL containing ai001.huahuoai.com
open Chrome tabs with visible title containing Dify
```

Observed:

```text
matching open tab count: 0
```

Interpretation:

- There was no existing logged-in production Dify tab that could be safely
  claimed for authenticated baseline testing.
- The browser-side blocker from the earlier direct navigation attempt is not
  treated as production Dify downtime.
- Authenticated existing-app open/message/reply/refresh/history/logout testing
  remains incomplete.

Root server read-only internal refresh at the same time:

```text
time: 2026-06-06T20:11:37+08:00
host: AI-01
http://127.0.0.1:8081/ -> 307
http://127.0.0.1:8081/signin -> 200
http://127.0.0.1:8081/apps -> 200
http://127.0.0.1:8081/console/api/account/profile -> 401
openresty-prod: Up 10 days
docker-nginx-1: Up 5 months
docker-web-1: Up 5 months (unhealthy, historical healthcheck issue)
docker-api-1: Up 5 months
docker-nginx-1 recent error/exception/traceback/5xx matches: 0
docker-web-1 recent error/exception/traceback/5xx matches: 0
docker-api-1 recent error/exception/traceback/5xx matches: 1
```

Gate markers:

```text
authenticated_baseline: NO_GO
existing app message: NO_GO
streaming reply: NO_GO
refresh: NO_GO
history: NO_GO
logout: NO_GO
profile 401: PASS
new 5xx: NONE
api recent log match review: REQUIRED
```

## Real Chrome Refresh 2026-06-06 12:45 Asia/Shanghai

Mode: real Chrome browser through the Codex Chrome extension. No cookies, local
storage, session storage, request headers, CSRF values, Authorization tokens or
passwords were read or recorded.

Route:

```text
https://ai001.huahuoai.com/apps
```

Observed:

```text
finalUrl: https://ai001.huahuoai.com/signin
title: Dify
visible page: Dify login page
console/dev error count: 0
```

Interpretation:

- Current Chrome profile still has no authenticated Dify session for
  `https://ai001.huahuoai.com`.
- `/apps` redirecting to `/signin` remains expected unauthenticated behavior.
- Authenticated existing-app open/message/reply/refresh/history/logout testing
  remains incomplete and continues to block any future public OpenClaw route or
  production sidecar deployment.

Gate markers:

```text
authenticated_baseline: NO_GO
existing app message: NO_GO
streaming reply: NO_GO
refresh: NO_GO
history: NO_GO
logout: NO_GO
profile 401: PASS
new 5xx: NONE
```
