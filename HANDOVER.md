# OpenClaw 短视频分析 Sidecar — 交接文档（详细版）

Date: 2026-06-12 Asia/Shanghai
Repo: github.com:Xieyangzai/dify_openclaw_viedo (origin/master)
HEAD: `6f7b0a9`（已 push origin）
权威环境：root 服务器（AI-01，别名 `root`，通过 ssh-skill 连接）

> 本文件汇总当前**全部**状态：项目定位、架构（已迁移到 Vite 构建）、功能、部署锚点、
> 测试、对话分支、验证证据、关键决策/契约、构建-部署-验证-回滚流程、并发协作情况、
> 已知问题与剩余工作。新接手者只读本文件 + 仓库即可继续，无需任何外部服务。

---

## 0. 一句话现状
OpenClaw 自有的短视频分析产品页（Dify 旁车），入口
`https://www.huahuoai.com/ai/openclaw-lab/`：OpenClaw 自有账号**首页内联登录** →
ChatGPT 风格单列对话 → 粘贴抖音视频链接 / 上传视频文件 → Doubao(`doubao-seed-2-0-pro`)
多模态分析 → Markdown 结果回填；会话/主题/置顶/归档/改名等偏好**跨设备持久化**。
前端已从"内嵌 Python 字符串"迁移为 **Vite 构建的静态资源**，由 bridge 同源托管。
root 已部署最新构建（`webdist/index-0PNgqsbK.js`），公共路由 200/200/401，Dify 核心容器未受影响。

---

## 1. 架构与组件

### 1.1 sidecar 容器（compose project `openclaw-video`，root 上）
- `openclaw-video-openclaw-bridge-1`（:18181，内网）：FastAPI，提供页面 + `/openclaw-api/*`。
  **唯一允许接触 Dify 网络的组件。** 现在它**静态托管**前端构建产物（见 1.3）。
- `openclaw-video-video-analysis-worker-1`：异步视频分析 worker（链接 + 上传两条路径）。
- `openclaw-video-openclaw-gateway-1`（:18789 内网，WS v3）：文本聊天 agent（Doubao provider）。
- `openclaw-video-bridge-postgres-1`（:5432 内网）：用户/会话/任务/结果 + **新增 `bridge_user_prefs`**。
- `openclaw-video-dify-openclaw-bridge-1`、`openresty-prod`：网关路由。

### 1.2 Dify 核心容器（**绝不可动**）
`docker-api-1` / `docker-web-1` / `docker-nginx-1`。每次部署后必须确认其容器 Id 与 StartedAt 不变。
当前锚点：`docker-web-1`/`docker-nginx-1` = `2026-01-05T11:17Z`；`docker-api-1` =
`2026-06-09T13:36:22Z`（在本轮工作**之前**就已被重启过，非本项目所为，已作为基线记录）。

### 1.3 前端架构（**已迁移，重点**）
- 源码：`openclaw-video/web/`（**Vite + 原生 TS + CSS，无框架/路由/组件库**）。
  - `web/index.html`：应用外壳（落地页 + 内联登录 + chatApp + 弹窗/toast/菜单），**保留全部契约元素 ID**。
  - `web/src/main.ts`：全部页面 JS（约 1900+ 行，单文件，`// @ts-nocheck`）。
  - `web/src/styles.css`：设计令牌 + 组件 + 深色模式 + markdown 样式。
  - 依赖：`marked` + `dompurify`（Markdown 渲染 + XSS 清洗），`vite` + `typescript`（devDeps）。
- 构建：本地 `cd openclaw-video/web && npm run build` → 产物输出到
  **`openclaw-video/src/openclaw_video/webdist/`**（`base:'./'` 相对路径、内容哈希、**已提交 git**）。
  **镜像不装 node**：本地构建、提交 `webdist`，靠 bridge 的 `COPY src` 进镜像。
- bridge 托管（`bridge_app.py`）：
  - lab 路由（`/openclaw-lab/`、`/ai/openclaw-lab/`）返回 `webdist/index.html`；无斜杠路由 308 跳到带斜杠。
  - 资源路由 `/{prefix}/openclaw-lab/assets/{path}` 用 `FileResponse` 服 `webdist/assets/*`（防目录穿越、长缓存）。
  - `webdist` 路径解析：`__file__` 同级优先，回退 `/app/src/openclaw_video/webdist`（pip 安装后靠 COPY src 入镜像）。
  - OpenResty 已验证会把 `/ai/openclaw-lab/assets/*` 子路径转发到 bridge（公网 js/css 200）。

---

## 2. 已交付功能（全部已部署 root + 验证 + 提交）

按时间线/里程碑：

| 里程碑 | tag（`phase4-openclaw-*`）| 内容 |
|---|---|---|
| M2 续 | `…-m2-conversation-state-machine-20260610` | 完整会话状态机（派生式，不改 DB）+ 分支对话（混合：固定话术 + agent 注入真实分析摘要）+ 错误映射 |
| 上传真分析 | `…-upload-real-analysis-20260610` | worker 把上传文件 base64 内联给 Doubao 直接分析，补齐"链接 + 上传"两种输入 |
| M3 知识固化 | `…-m3-knowledge-coaching-20260610` | 5 维度分析框架 + 6 条画面原则按意图注入教练提示词；修 Gateway 长生成 30s→120s 超时（可配） |
| UI 产品化 | `…-ui-overhaul-20260610` | 深色模式、会话搜索/菜单、用户菜单、消息复制、移动抽屉、a11y、统一 SVG 图标 |
| 方案B迁移 | `…-web-vite-migration-20260611` | 把 ~3300 行内嵌 `LAB_PAGE_HTML` 抽成 Vite 工程，bridge 静态托管，改造契约测试 |
| prefs 持久化 | `…-prefs-persistence-20260611` | `bridge_user_prefs(JSONB)` 表 + `GET/PUT /openclaw-api/prefs`；主题/会话 override 跨设备 |
| Markdown | `…-markdown-rendering-20260611` | marked+DOMPurify 渲染助手消息、代码块复制、XSS 清洗 |
| 消息/会话高级 | `…-msg-session-ops-20260611` | 消息复制/重生成/编辑重发/删除；会话置顶/归档/批量删除（prefs 持久） |
| 虚拟滚动+a11y | `…-virtualization-a11y-20260611` | `content-visibility:auto` 长会话性能；弹窗焦点陷阱、菜单方向键、`:focus-visible` |

并发会话（见 §6）在以上基础上又交付（已在 master，commits `1a91ed5..298a16d`）：
- **首页内联登录**（账号/密码直接在落地页 hero 填写，无需先点"登录"；`openLogin`/`loginPanel`/`closeLogin` 保留为存根满足契约）。
- **每条消息显示时间**（`.cg-msg-time`，今天 HH:MM / MM-DD HH:MM）+ **逐条复制**。
- **TikTok / B 站链接**支持（`VIDEO_LINK_RE` 扩展；resolver 侧相应处理）。
- **要求 agent 用 Markdown 输出**；历史里展示视频链接；read-check 回复持久化视频链接。
- **诊断抽屉隐藏**（`#devDrawer class="cg-dev-hidden" hidden"`，移除 shell 中"开发详情/验证工具"文案；按钮 ID 仍在供契约/自动化）。
- 会话标题默认"短视频分析助手"、助手标签"分析助手"、composer/标签细化、异步对话更新防护。

`git tag -l "phase4-openclaw-*"` 可看全部 tag。

---

## 3. 关键 API（bridge，owner 按 principal 隔离）
- `POST /openclaw-api/auth/login`（账号密码 → HttpOnly session）；`/auth/logout`；`GET /me`。
- `GET/POST /openclaw-api/sessions`、`GET /sessions/{id}/messages`。
- `POST /openclaw-api/chat`（带 `video_url` 则转 create_job；否则护栏→意图→状态机→Gateway agent）。
- `POST /openclaw-api/jobs`（链接分析）、`POST /openclaw-api/uploads`（上传分析）、`GET /jobs/{id}`、`/jobs/{id}/result`、`/jobs/{id}/events`。
- `POST /openclaw-api/video-link/read-check`（预检，`model_invoked=false`）。
- **`GET/PUT /openclaw-api/prefs`**（新增；JSONB，64KB 上限，非 object 体 400）。存主题 + 会话 override（改名/删除/置顶/归档）。
- 诊断/自检/安全检查/登录后验收端点（`identityDiagnostics`/`runSelfTest`/`runSecurityTest`/`runPostLoginAcceptance`）。
- 4 个前缀同时注册：`/openclaw-api`、`/ai/openclaw-api`、`/api/openclaw-api`、`/console/api/openclaw-api`。前端 `apiPrefix` 据路径自选。

---

## 4. 对话状态机与分支（`agent_persona.py`，Bridge 侧规则）
状态（派生式，不落库）：new / collecting_intent / waiting_for_video / waiting_for_clarification /
video_analyzing / video_analyzed / feedback_given / follow_up / error_recovering。
- **固定话术**（不调 agent）：新用户引导、collecting_intent（赛道/目标用户/变现）、waiting_for_video（引导发抖音链接/上传）、
  平台护栏（非抖音/主页链/提示注入/跑题）、错误映射 `error_reply_for`（tool_timeout/url_rejected/tool_failed/upload_too_large）。
- **agent 生成**（feedback_given/follow_up）：注入**真实分析摘要** + 分支指令（改开头/改脚本/复拍/为什么不爆）+ 5 维度/画面方法论。
  关键：分析走 worker（不在 Gateway 记忆里），必须由 Bridge 注入摘要，杜绝追问泛化/幻想。

---

## 5. 测试与验证

### 5.1 本地单测
`PYTHONPATH=openclaw-video/src .phase1-sandbox/bridge-api-venv/Scripts/python.exe -m unittest discover openclaw-video/tests`
→ **325 tests，仅 1 条既有无关失败** `test_identity_diagnostics_fails_closed_for_multiple_current_workspaces`
（早于本期工作，与本期无关，**待排查**）。
前端：`cd openclaw-video/web && npm run build`；可对构建产物用 node + playwright-core 渲染检查（见 5.3）。

### 5.2 root 端到端验证证据（`artifacts/evidence/phase4/`）
- `openclaw-dialogue-branch-root-evidence-20260611.json`：page_shell/login/collecting_intent/casual_agent 等分支 PASS（inlineLogin=true，无横向溢出）。
- `openclaw-web-dialogue-link-upload-root-evidence-20260611.json`：登录 + 抖音链接 composer 全链路分析 PASS（assistants=2，run_state="结果已就绪"，copyVisible/timeVisible=true，devHidden=true，console_error=0）。
- `openclaw-markdown-render-root-20260611.json` / `openclaw-history-video-url-render-root-20260611.json`：Markdown 渲染、历史视频链接展示。
- `openclaw-upload-real-analysis-root-evidence-20260610.json`：28.6MB mp4 上传 → succeeded → 1936 字真实分析。
- `openclaw-m2-…/m3-…/ui-overhaul-…/real-video-link-e2e-…` 等：各里程碑脱敏证据 + 截图。
- 已覆盖分支：内联登录、新会话问候、collecting_intent、waiting_for_video、非抖音/主页/注入/跑题护栏、
  真实抖音视频全链路分析、追问、时间戳、逐条复制；并发会话另补充了 link/upload composer 验收。

### 5.3 本地渲染检查（无 npm 版 playwright）
node playwright-core 在 `.phase1-sandbox/openclaw-3.13/node_modules`；chromium 在
`~/AppData/Local/ms-playwright/chromium-1223`（用 `executablePath` 指向 `chrome-win64/chrome.exe`，
版本与 playwright-core 内置 shell 不符，必须显式指定）。

### 5.4 已知未单独 e2e 的分支（建议补）
连续多视频 `current_video` 切换、解析失败后的 error_recovering 文本追问、超大上传 `upload_too_large` 友好回复（已单测，未 root e2e）。

---

## 6. 并发协作情况（重要）
本期存在**两个会话并行修改同一仓库**：本会话交付了 M2续/上传/M3/UI 产品化/方案B 5 阶段；
另一会话在其基础上（`1a91ed5..298a16d`，已在 master）交付了内联登录、时间戳、TikTok/B站、
Markdown-required、隐藏诊断、视频链接持久化、标签/composer 细化、对话分支验收证据，并**已 build webdist + 部署 root**。
两边工作已合并在 master（HEAD `6f7b0a9`），互不冲突。
本会话最后修了一处遗留 RED（隐藏诊断后 `test_bridge_app` 仍断言旧诊断文案 → 已对齐，commit `6f7b0a9`）。
**接手提醒**：若仍有第二会话在跑，提交/push 前先 `git pull --rebase`，改前确认无未提交并发改动。

---

## 7. 构建 / 部署 / 验证 / 回滚

### 7.1 改前端（web/）
1. 改 `openclaw-video/web/{index.html,src/main.ts,src/styles.css}`。
2. `cd openclaw-video/web && npm run build`（产物到 `src/openclaw_video/webdist/`，**先停掉任何占用 webdist 的本地静态服务**，否则 Windows EBUSY）。
3. 本地渲染自检（5.3）；本地单测（5.1）。
4. 部署：清远端 `webdist/assets/*` → LF 不影响 js/css（按字节上传）→ 传 `index.html` + 新 `assets/*` 到
   `…/current/openclaw-video/src/openclaw_video/webdist/` →
   `bash …/current/scripts/root_rebuild_bridge_fast.sh`（期望 `bridge_fast_rebuild=PASS`，只重建 bridge）。
5. 验收：`curl` 页面 200 + 资源 js/css 200 + 未认证 API 401；`docker inspect` Dify 三容器 Id/StartedAt 不变；
   node playwright 真实登录渲染（无 code error、无横向溢出）。

### 7.2 改后端（bridge `*.py`）
1. 本地改 + 单测。2. **字节级 CRLF→LF** 转换后用 `ssh_upload.py`（命令前加 `MSYS_NO_PATHCONV=1`）传到
   `…/current/openclaw-video/src/openclaw_video/<file>.py`，**先 cp .bak 备份**。
3. root 上 `python3 -m py_compile`。4. `root_rebuild_bridge_fast.sh`。5. 同 7.1 验收。
   改 worker 用快速分层重建（FROM 现有 worker 镜像 COPY src + `pip install --no-deps` + `up -d --no-deps --force-recreate video-analysis-worker`），**勿 `--build` 全量**。

### 7.3 改数据库（仅附加，谨慎）
`bridge_user_prefs` 已应用（migration `database/migrations/002_user_prefs.sql` + rollback `…/rollback/002_user_prefs_down.sql`）。
新迁移须**手动**应用（compose 的 initdb.d 只在空库跑）：先
`docker exec <PG> sh -c 'PGPASSWORD=$POSTGRES_PASSWORD pg_dump -U bridge -d bridge --schema-only' > 快照`，
再 `docker exec -i <PG> sh -c 'PGPASSWORD=$POSTGRES_PASSWORD psql -U bridge -d bridge -v ON_ERROR_STOP=1' < 迁移.sql`。
PG 容器：`openclaw-video-bridge-postgres-1`，库/用户 `bridge`。回滚=应用 down.sql（仅 drop 附加表）。

### 7.4 回滚
- 前端/后端：用 `*.bak-*` 覆盖回 + `root_rebuild_bridge_fast.sh`；或 `git revert <commit>` 后重建。
- 旧 webdist 资源被 emptyOutDir 清掉，回滚靠 git（`webdist` 已提交）。
- sidecar 整体：`openclaw-video/rollback-runbook.md`（不影响 Dify）。
- 回滚后必跑 §7.1 步骤 5 的公共路由 + Dify 不变量验收。

---

## 8. 关键决策 / 契约（务必延续）
- **规则兜底 + agent 生成**：链接识别/意图/状态机/错误映射/护栏在 Bridge 侧规则（稳定可单测），agent 只做自然语言生成（含注入真实分析摘要）。
- **两种输入**：抖音链接（resolver 拿 douyinvod CDN 直链 → Doubao 直链分析）；上传文件（worker base64 内联 → Doubao）。**抖音"图文笔记 /note/（aweme_type=2）"无视频流，分析必失败**——属预期。
- **无浏览器存储**：UI 契约测试禁止 `localStorage`/`Cookie`；偏好一律走服务端 `prefs` API。session 为 HttpOnly。
- **同源**：前端与 API 同源由 OpenResty 路由到 bridge；不暴露 gateway/worker/postgres 公网。
- **契约元素 ID 必须保留**：`loginAccount/loginPassword/loginButton/openLogin/landingPage/chatApp/authStatus/
  identityDiagnostics/runPostLoginAcceptance/runSelfTest/runSecurityTest/createSession/sessionId/sessionList/
  videoUrl/prompt/readVideoLink/submitJob/pollJob/videoFile/uploadJob/uploadSmoke/output`。改 UI 先跑契约测试。
- **保密**：账号/密码/cookie/token/数据库 URL/密钥/模型原文，一律不入文档/日志/证据/git。
  `agent.md`（含测试账号密码）**已加入 .gitignore，绝不提交**。
- **root-first + Dify 不可动**：只部署可回滚的 sidecar 变更；严禁重启/重建 Dify api/web/nginx，严禁改 Dify compose。
- **每个大改动**：提交 + 部署后打 `phase4-openclaw-<描述>-<日期>` tag；push 前与用户确认（并发时先 rebase）。
- **JS/CSS 历史陷阱（仅 `LAB_PAGE_HTML` 时代，现已不适用）**：迁到 web/ 后是真 .ts/.css，无 Python 转义陷阱；放心用 `\n`、模板字面量、Unicode。

---

## 9. 当前部署锚点
- HEAD：`6f7b0a9`（origin/master 同步）。
- root current release：`/app/bin/openclaw-video/current` → `…/releases/video-agent-fix-20260608T0001`。
- bridge 镜像：`openclaw-video-openclaw-bridge:fast`；前端构建：`webdist/index-0PNgqsbK.js` + `…css`（已部署）。
- 公共路由：huahuo 根 200 / openclaw 页面 200 / 未认证 API 401。
- Dify 核心容器 StartedAt：web/nginx `2026-01-05T11:17Z`、api `2026-06-09T13:36:22Z`（均未因本期工作改变）。
- 模型：`doubao-seed-2-0-pro`，base `https://ark.cn-beijing.volces.com/api/coding/v3`（ARK key 在 root `/run/secrets/douyin_chong_env`）。

---

## 10. 剩余工作 / 建议
1. 排查既有无关单测失败 `test_identity_diagnostics_fails_closed_for_multiple_current_workspaces`（早于本期，长期挂红）。
2. 补 root e2e：连续多视频 `current_video` 切换、解析失败后文本追问的 error_recovering、超大上传 `upload_too_large`。
3. `web/src/main.ts` 仍是单文件（~1900 行）：按计划可拆 `api/sessions/messages/menus/prefs/...` 模块（纯重构、零行为变更）。
4. 真正窗口化虚拟滚动（当前 `content-visibility:auto` 已覆盖绝大多数场景）。
5. 独立多分区设置页（当前设置在用户菜单内）。
6. TikTok/B站 解析的真实 root 验收（链接正则已支持，需真实链接验证 resolver 全链路）。
7. 前端可加 eslint/tsc 到 CI（已 `// @ts-nocheck`，类型检查暂关）。

---

## 11. 常用路径速查
- 前端源码：`openclaw-video/web/`（`index.html`、`src/main.ts`、`src/styles.css`、`package.json`、`vite.config.ts`）。
- 前端构建产物（已提交）：`openclaw-video/src/openclaw_video/webdist/`。
- 后端：`openclaw-video/src/openclaw_video/`（`bridge_app.py`、`agent_persona.py`、`worker_service.py`、`douyin_legacy_adapter.py`、`douyin_wrapper.py`、`postgres_store.py`、`session_store.py`、`openclaw_gateway.py`）。
- 测试：`openclaw-video/tests/`（`test_bridge_app.py`、`test_agent_persona.py`、`test_openclaw_lab_ui_contract.py`、`test_*` …）。
- 迁移：`openclaw-video/database/migrations/`（`001_init.sql`、`002_user_prefs.sql`）+ `…/rollback/`。
- 部署脚本：`…/current/scripts/root_rebuild_bridge_fast.sh`（root 上）。
- 证据：`artifacts/evidence/phase4/`。
- 方案文档：`openclaw_video_agent_execution_plan.md`、`openclaw-engineering-baseline.md`、`openclaw-chat-ui-agent-execution-plan.md`、`第一版执行方案.md`（第 9–13 章状态机/分支/提示词/错误映射）。
- ssh：所有远端操作走 ssh-skill（`~/.claude/skills/ssh-skill/scripts`，别名 `root`）；`ssh_execute.py`/`ssh_upload.py`（上传加 `MSYS_NO_PATHCONV=1`，脚本用绝对路径）。
