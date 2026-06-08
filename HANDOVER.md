# OpenClaw 短视频分析 Sidecar — 交接文档

Date: 2026-06-08 Asia/Shanghai
Repo: github.com:Xieyangzai/dify_openclaw_viedo (origin/master)
HEAD: e7bcc4c

本文件供任务交接使用，汇总当前状态、里程碑、剩余工作、关键决策、部署/回滚方法。
权威文档以本仓库内的以下文件为准，交接无需任何外部服务：

- `openclaw_video_agent_execution_plan.md`（总目标与边界）
- `openclaw-engineering-baseline.md`（工程基线与纪律）
- `openclaw-chat-ui-agent-execution-plan.md`（本期 ChatGPT UI + Agent 任务的分阶段计划）
- `artifacts/evidence/phase4/`（脱敏部署/验收证据）

---

## 1. 项目是什么

在 Huahuo 域名上运营一个 OpenClaw 自有的短视频分析产品页，作为 Dify 的旁车
（sidecar），与 Dify Web 完全独立。

- 用户入口：`https://www.huahuoai.com/ai/openclaw-lab/`
- 登录：OpenClaw 自有账号/密码（Bridge 服务端校验 Huahuo 前端用户系统），
  签发 OpenClaw 自有 HttpOnly session；**不依赖 Dify 登录、不复用 cookie**。
- 视频分析：视频链接读取模式（URL guard → 重定向复验 → Worker →
  douyin_chong UniversalVideoResolver → 直连候选 → 模型分析），外加视频文件上传。

## 2. 架构与组件（root 服务器）

服务器别名 `root`（AI-01，123.57.81.44，密码认证，通过 ssh-skill 连接）。

OpenClaw sidecar 容器（compose project `openclaw-video`）：

- `openclaw-bridge`（:18181）：浏览器页面 + API，UI 内嵌在 `bridge_app.py` 的
  `LAB_PAGE_HTML`。唯一允许接触 Dify 网络的组件。
- `video-analysis-worker`：异步视频分析 worker。
- `openclaw-gateway`（:18789 私有，WS v3）：跑文本聊天 agent（Doubao provider）。
- `bridge-postgres`（:5432 私有）：用户/会话/任务/结果。
- `dify-openclaw-bridge`（:18182）、`openresty-prod`：网关路由。

Dify 核心容器（**不可动**）：`docker-api-1` / `docker-web-1` / `docker-nginx-1`
等，自 2026-01-05 起未重启/重建，每次部署后必须确认其容器 ID 与 StartedAt 不变。

部署方式：release 目录 + `current` 软链接。当前
`current -> /app/bin/openclaw-video/releases/video-agent-fix-20260608T0001`。
UI/后端源码编进 `openclaw-video-openclaw-bridge:fast` 镜像（非挂载），改后需重建镜像。

## 3. 已完成里程碑

| 里程碑 | tag | 内容 |
|---|---|---|
| iOS 级 UI 打磨 | `phase4-openclaw-ui-ios-grade-polish-20260608` | 设计令牌、阴影、44px 点击目标、AA 对比度 |
| video-agent 收尾 | `phase4-openclaw-video-agent-finalize-20260608` | agent_video_cli、adapter 增强、审计同步、GO |
| M1 ChatGPT 风格 UI | `phase4-openclaw-chatgpt-ui-20260608` | 两栏布局 + 聊天内视频输入（链接/上传统一入口） |
| M1.1 忠实 ChatGPT 化 | `phase4-openclaw-chatgpt-faithful-ui-20260608` | 去步骤条、窄侧栏、居中单列、胶囊输入、上传进度条、截图内联 |
| M2 Agent 人设+护栏 | `phase4-openclaw-m2-agent-persona-guardrails-20260608` | 短视频教练人设注入、意图识别、平台护栏 |

均已部署 root 并真实登录/上传端到端验证通过；证据在 `artifacts/evidence/phase4/`。

### M2 关键修复（由全场景遍历测试发现）

- 问题 A：纯聊天曾返回英文通用 OpenClaw 开场白 → 首轮注入中文短视频教练人设
  （`agent_persona.py` 的 `SYSTEM_PERSONA`，在 `bridge_app.py` chat 端点接入）。
- 问题 B：YouTube/B站/小红书等非抖音链接会让 agent 幻想"转录字幕"等不存在能力
  → Bridge 侧 `guardrail_for_message()` 对非抖音平台/抖音主页链接返回固定中文
  回复，不调用 agent。
- 上传占位文案由英文改为干净中文（`worker_service.py`）。

## 4. 剩余工作

按 `openclaw-chat-ui-agent-execution-plan.md`：

- [ ] M2 续：完整会话状态机与分支对话（第一版方案第 10 章；当前只做了人设+护栏+意图识别）
- [ ] M3：必要的 skill 固化（第一版方案 5.x）
- [ ] M4：端到端测试补充
  - 真实抖音视频链接全链路（链接读取 → 分析 → 结果回填 + 截图内联），**需要一条真实抖音 URL**
  - 连续多视频对话时 `current_video_id` 切换
  - 真实模型分析结果的截图帧 URL 展示验证
- 已知既有单测失败（与本期工作无关，待排查）：
  `test_bridge_app.test_identity_diagnostics_fails_closed_for_multiple_current_workspaces`

## 5. 关键决策（务必延续）

- **规则兜底 + agent 生成**：链接识别、意图分类、错误映射、平台护栏放在 Bridge 侧
  用规则实现（稳定、可单测），agent 只负责自然语言生成；用 skill 固化 agent 行为。
- **上传只判断"有视频文件"**：agent 不读上传视频内容，真实处理交专门 worker/脚本。
- **Root-first**：root 是权威环境，只部署可回滚的 sidecar 变更；
  **严禁**重启/重建 Dify api/web/nginx，严禁改 Dify compose。
- **保密**：账号、密码、cookie、token、数据库 URL、密钥、模型原文，
  一律不写入文档/日志/证据/git。`agent.md` 含测试账号密码，**不提交 git**。
- **UI 元素 ID 契约**：重设计 UI 必须保留 `loginAccount/loginPassword/loginButton/
  authStatus/identityDiagnostics/runPostLoginAcceptance/runSelfTest/runSecurityTest/
  createSession/sessionId/videoUrl/prompt/readVideoLink/submitJob/pollJob/videoFile/
  uploadJob/uploadSmoke/output` 等，否则破坏自动化与契约测试。
- **每个大改动做 git 版本管理**：提交 + 部署后打里程碑 tag（`phase4-openclaw-<描述>-<日期>`），
  push 前与用户确认。
- **编码陷阱**：`LAB_PAGE_HTML` 是 Python 三引号字符串，JS 字符串里写 `\n` 会被
  Python 转成真实换行而破坏脚本；上传到 Linux 须用字节级 CRLF→LF 转换避免中文损坏。

## 6. 如何部署到 root

前提：通过 ssh-skill 连接（脚本在 `~/.kiro/skills/ssh-skill/scripts`，别名 `root`）。

1. 本地改 `openclaw-video/src/openclaw_video/*.py`，跑测试：
   ```
   $env:PYTHONPATH='openclaw-video\src'
   .\.phase1-sandbox\bridge-api-venv\Scripts\python.exe -m unittest discover openclaw-video\tests
   ```
2. git 提交（仅相关文件）。
3. 字节级 LF 转换后上传（避免中文损坏）：
   ```python
   data = open(SRC,'rb').read().replace(b'\r\n', b'\n'); open(DST,'wb').write(data)
   ```
   用 `ssh_upload.py`（命令前加 `MSYS_NO_PATHCONV=1`）传到
   `/app/bin/openclaw-video/current/openclaw-video/src/openclaw_video/<file>.py`。
   上传前先 `cp` 备份原文件。
4. 在 root 校验语法：`python3 -m py_compile openclaw_video/<file>.py`。
5. 重建 Bridge（只重建 bridge，不碰其他）：
   ```
   bash /app/bin/openclaw-video/current/scripts/root_rebuild_bridge_fast.sh
   ```
   期望输出 `bridge_fast_rebuild=PASS`。
   - 若改的是 worker（`worker_service.py` 等）：用快速分层重建
     （基于现有 worker 镜像 COPY src + `pip install --no-deps`，再
     `docker compose ... up -d --no-deps --force-recreate video-analysis-worker`）。
     不要用 `--build` 全量重建，会因联网下载依赖极慢。
6. 部署后验收：
   - `curl` 检查 huahuo 根 200 / openclaw 页面 200 / 未认证 API 401
   - `docker inspect` 确认 docker-api-1/web-1/nginx-1 的 Id 与 StartedAt 未变
   - 真实登录端到端（Playwright，账号密码仅作运行输入，不入证据）
7. 抓脱敏证据到 `artifacts/evidence/phase4/`，打 tag，push（先与用户确认）。

本地无 npm 版 Playwright，用 sandbox 的 `playwright-core` +
缓存 chromium（`~/AppData/Local/ms-playwright/chromium-1223`）做渲染/截图/真实登录测试。

## 7. 如何回滚

- Bridge UI/后端回滚：用上传前的 `*.bak-*` 备份覆盖回原文件，重跑
  `root_rebuild_bridge_fast.sh`；或切 `current` 软链接回上一个 release 后重建。
- sidecar 整体回滚：见 `openclaw-video/rollback-runbook.md`
  （`docker compose -p openclaw-video ... down`，不影响 Dify）。
- git 回滚：`git revert <commit>` 或 checkout 上一个里程碑 tag。
- 回滚后必须复跑第 6 步的公共路由 + Dify 不变量验收。

## 8. 当前部署锚点

- root current release：`video-agent-fix-20260608T0001`
- bridge 镜像：`openclaw-video-openclaw-bridge:fast`
- 最新提交：`e7bcc4c`（已 push origin/master）
- 公共路由：huahuo 根 200 / openclaw 页面 200 / 未认证 API 401
- Dify 核心容器 StartedAt：2026-01-05T11:17:xxZ（未变）
