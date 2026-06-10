# OpenClaw 聊天式 UI + 视频分析 Agent 执行计划

Date: 2026-06-08 Asia/Shanghai
Owner: root thread
Status: 计划已制定，待按阶段执行

本计划是本次大任务的权威执行文档。它在
`openclaw_video_agent_execution_plan.md` 和
`openclaw-engineering-baseline.md` 的约束下展开，不改变已确立的边界
（OpenClaw 独立站点、自有登录、root-first、不动 Dify 容器）。

---

## 1. 任务目标

1. **登录后界面改成 ChatGPT 风格**：登录页保持不变；登录后从"工作台多面板"
   改成单列对话式界面（左侧历史会话列表 + 中间单列对话流 + 底部统一输入区）。
2. **视频上传 / 视频链接直接在聊天窗口内完成**：取消独立的"视频分析"面板，
   把"链接输入"和"本地文件上传"合并进底部聊天输入区（链接直接粘贴进输入框，
   上传通过输入区的附件按钮）。
3. **Agent 身份与能力落地**：参考第一版执行方案第 9–13 章，让 OpenClaw agent
   具备短视频教练人设、意图识别、分支对话、提示词系统、错误处理。必要时新增
   skill 固化稳定性。
4. **测试**：本地上传视频、视频链接两条路径都要在 root 上跑通并留证据。
5. **每个大改动做 git 版本管理**（提交 + tag + 部署后证据）。

---

## 2. 现状基线（已核查）

- 登录后是多面板"工作台"：左会话栏 + 中聊天栏 + 右"视频分析/结果/诊断"工具栏。
- 聊天走 `POST /openclaw-api/chat` → OpenClaw Gateway WS v3 agent（Doubao provider）。
  chat 接口已有"带 `video_url` 则转 `create_job`"的雏形。
- 视频分析走 `POST /openclaw-api/jobs`（链接）和 `POST /openclaw-api/uploads`
  （上传）→ `VideoAnalysisWorker` → `douyin_wrapper` / 上传文件级校验。
- 链接读取预检走 `POST /openclaw-api/video-link/read-check`。
- 上传当前是"文件级校验"占位（`_analyze_uploaded_video`），尚未接入真实多模态理解。
- agent 身份在 Gateway 侧，无短视频教练人设、无意图识别 / 分支对话 / 错误映射。
- UI 全部内嵌在 `bridge_app.py` 的 `LAB_PAGE_HTML`，元素 ID 受自动化测试约束，
  必须保留：`loginAccount/loginPassword/loginButton/authStatus/identityDiagnostics/
  runPostLoginAcceptance/runSelfTest/runSecurityTest/createSession/sessionId/
  videoUrl/prompt/readVideoLink/submitJob/pollJob/videoFile/uploadJob/uploadSmoke/output`。

---

## 3. 范围边界（不做 / 不碰）

- 不改 Dify `api`/`web`/`nginx` 容器，不改 Dify compose。
- 不动登录页视觉（用户明确说"除登录界面之外"）。
- 不把 Gateway/Worker/Postgres 暴露公网。
- 不在文档/日志/证据记录账号、密码、cookie、token、密钥、模型原文。
- 第一版边界沿用：主支持抖音链接；上传作为输入路径；不做严格多视频逐帧对比
  （可轻量对比）；不做强制用户画像采集。

---

## 4. 阶段拆解

### 阶段 A：ChatGPT 风格登录后界面（UI 重构）

目标：登录后界面从多面板改为单列对话式，视频输入并入聊天输入区。

A1. 布局重构（`bridge_app.py` 的 chatApp 部分 + CSS）
- 改成两栏：左侧会话历史侧栏（可折叠），右侧单列对话区。
- 对话区：顶部细标题栏（当前会话名 + 状态徽章），中间消息流（ChatGPT 式
  用户右/助手左气泡、头像、留白），底部固定输入区。
- 移除右侧"视频分析 / 结果与状态"独立工具栏面板；其能力并入对话流与输入区。
- 诊断 / 验收 / 自检 / 安全检查 / 原始 JSON 收进一个"开发者/诊断"折叠抽屉
  （二级，不占主视觉），保留所有按钮 ID 供测试。

A2. 统一输入区（聊天即视频入口）
- 输入区一个多行文本框 `prompt` + 发送按钮 `sendChat`。
- 左侧"＋"附件按钮触发隐藏的 `videoFile`，选中文件后在输入区上方显示文件 chip。
- 用户在文本框粘贴视频链接时，前端识别链接（复用第一版链接正则），显示
  "检测到视频链接"提示条。
- 发送逻辑统一：
  - 有附件文件 → 走 `/uploads`（保留 `uploadJob` 行为，UI 隐藏旧按钮）。
  - 文本含视频链接 → 走 `/jobs`（保留 `submitJob` 行为）。
  - 纯文本 → 走 `/chat`（agent 对话）。
- 保留 `videoUrl/readVideoLink/submitJob/pollJob/uploadJob/uploadSmoke` 等元素
  （隐藏或移入诊断抽屉），确保契约测试与验收脚本不破。

A3. 消息流渲染增强
- 任务型消息（分析进行中/完成/失败）渲染为带状态的助手气泡，内嵌"刷新状态"。
- 上传/链接显示为用户气泡里的附件/链接卡片。
- 轮询 `pollJob` 改为发送后自动轮询，结果回填进对话流。

A4. 本地验证（设计审查 + 渲染诊断）
- 复用本地 Playwright 渲染：截图 + 零横向溢出 + 44px 点击目标 + AA 对比度。
- 20 项视觉设计自检，迭代到满分。

A5. 版本管理 + 部署
- 提交 UI 重构；部署 root（重建 Bridge）；线上验收（200/200/401、Dify 不变量）；
  抓桌面/移动端证据；打 tag。

### 阶段 B：Agent 身份与对话能力（第一版 9–13 章）

目标：让 agent 成为稳定的短视频教练，具备意图识别、分支对话、提示词、错误处理。

B1. Agent 身份与提示词系统（第 11 章）
- 设计 agent 系统提示词分层：身份(IDENTITY/SOUL) + 视频分析基础 + 知识库维度 +
  用户本轮要求 + 输出结构模板。
- 落地为 Bridge 侧可注入 Gateway 的系统上下文，或 OpenClaw agent 工作区文件。
- 知识库引用 `artifacts/knowledge-base-short-video/`。

B2. 意图识别（第 9 章）
- 实现意图枚举 + 规则识别词（analyze_my_video / benchmark / why_not_viral /
  rewrite_opening / rewrite_script / reshoot / picture / send_link 等）。
- 落地位置：Bridge 侧轻量规则前置分类（稳定、可测），把意图作为上下文传给 agent。

B3. 分支对话与会话状态机（第 10 章）
- 实现状态：new/collecting_intent/waiting_for_video/video_analyzing/
  video_analyzed/feedback_given/follow_up/error_recovering。
- 状态存于 session（扩展 session 元数据：stage / current_video / analysis_mode）。
- 各分支回复模板（新用户引导、无链接引导、主页链接、非抖音、解析失败、超时、
  开头改法、脚本改法、复拍、连续多视频、轻量对比）。

B4. 错误处理映射（第 13 章）
- 错误类型枚举 + 用户友好回复映射（NO_VIDEO_LINK / UNSUPPORTED_PLATFORM /
  PROFILE_LINK_NOT_SUPPORTED / DOUYIN_PARSE_FAILED / TOOL_TIMEOUT / ... ）。
- 对接 worker 现有 error_code（tool_timeout/url_rejected/tool_failed）做映射。

B5. 消息流向（第 12 章）
- 确认 session/init、chat、视频链接、追问四条消息流向在新 UI 下端到端一致。

### 阶段 C：Skill 固化（按需）

> 架构澄清（已与用户确认）：
> - 关键判定（链接识别、意图分类、错误映射、状态机）放在 Bridge 侧用规则实现
>   （稳定、可单测），agent 负责自然语言生成；skill 用于固化 agent 行为。
> - 上传文件：agent 只判断"是否有视频文件上传"，不读懂视频内容；真实视频
>   处理交给专门的视频处理脚本（worker）。agent 收到上传仅做"已收到文件 →
>   触发处理 → 回填结果"的对话编排。

目标：把上述能力中"必须稳定"的部分固化为 skill，降低 agent 漂移。

- 评估是否需要新增 skill：`video_link_detect`、`douyin_video_analyze`、
  `short_video_feedback`、`conversation_state`、`knowledge_retrieval`
  （第一版 5.x）。
- 优先级：链接识别和分析调用的稳定性最关键 → 先做 `video_link_detect` 与
  调用契约固化；反馈模板和知识检索次之。
- Skill 落地形式取决于 OpenClaw agent 的 skill 机制（部署在 Gateway agent 工作区）。
- 注意：Bridge 侧已有 url_guard / video_link_probe，可作为 skill 的底层；
  skill 主要固定"agent 行为"，不替代后端安全校验。

### 阶段 D：测试与验收

D1. 本地单元测试：扩展/新增测试覆盖意图识别、状态机、错误映射、链接识别。
D2. root 端到端测试（真实环境）：
- 视频链接路径：粘贴抖音链接 → 自动识别 → 读取预检 → 提交分析 → 轮询 → 结果回填对话流。
- 本地上传路径：选文件 → 上传 → 任务 → 结果回填。
- 对话路径：纯文本提问 → agent 教练式回复（意图正确、分支正确）。
- 错误路径：非抖音链接 / 主页链接 / 无效链接 / 超时 → 友好回复。
- 安全：内网/localhost/云元数据 URL 被拒（沿用现有安全测试）。
D3. 留脱敏证据到 `artifacts/evidence/phase4/`（截图 + JSON）。

D4. 版本管理：每阶段提交 + 部署后 tag + 证据。

---

## 5. 执行顺序与里程碑

```text
M1 (阶段A): ChatGPT 风格 UI + 聊天内视频输入   → 提交+部署+证据+tag
M2 (阶段B): Agent 身份/意图/分支/错误处理       → 提交+部署+证据+tag
M3 (阶段C): 必要 skill 固化                     → 提交+部署+证据+tag
M4 (阶段D): 端到端测试（链接/上传/对话/错误）   → 证据+最终 tag
```

每个里程碑独立可回滚；先 UI（用户当前最直接的痛点），再 agent 能力，再 skill，最后整体测试。

---

## 6. 风险与控制

| 风险 | 控制 |
|---|---|
| 改 UI 破坏自动化选择器/契约测试 | 保留所有受约束元素 ID，隐藏而非删除；改完先跑 UI 契约测试 |
| 聊天内统一入口路由判断错误（链接/上传/纯文本） | 前端 + 后端双重判定；后端 chat 已有 video_url 分流，扩展但不破坏 |
| 上传仅文件级校验，无真实理解 | 本阶段先打通链路与回填；真实多模态作为可选增强，明确标注 |
| agent 行为漂移 | 关键稳定性用 Bridge 侧规则 + skill 固化，而非纯提示词 |
| root 部署影响 Dify | 沿用 root-first 不变量校验；只重建 Bridge |
| 大改动丢历史 | 每里程碑提交+tag+证据 |

---

## 7. 当前进度

- [x] M1 阶段A：ChatGPT 风格 UI + 聊天内视频输入
      （commits b3f5373 + 03bcf48，tag phase4-openclaw-chatgpt-ui-20260608；
      已部署 root 并真实登录验收通过）
- [x] M1.1 忠实 ChatGPT 化：去步骤条、窄侧栏、居中单列对话、胶囊输入区、
      上传进度条、截图内联显示（commit af527f7，
      tag phase4-openclaw-chatgpt-faithful-ui-20260608；真实 28.6MB mp4 上传 e2e 通过）
- [x] M2 阶段B（部分）：短视频教练人设注入 + 意图识别 + 平台护栏
      （agent_persona.py + bridge_app.py chat 端点，commit e7bcc4c，
      tag phase4-openclaw-m2-agent-persona-guardrails-20260608；
      全场景遍历测试修复了"英文开场白"和"非抖音链接幻想能力"两个问题；
      19 条人设单测 + 83 条总测试通过）
      - [x] M2 续：完整会话状态机与分支对话（第一版方案第 10/11/13 章）
            派生式 stage（不改 DB）+ 混合回复（固定话术 + agent 注入真实分析摘要）；
            commit + 部署 root（仅重建 bridge）+ 对话端到端验收全过；
            证据 artifacts/evidence/phase4/openclaw-m2-conversation-state-machine-root-evidence-20260610.json
- [x] 上传真分析：worker 把上传文件 base64 内联给 Doubao 直接分析（绕开抖音解析），
      补齐"链接 + 上传"两种输入方式；真实 28.6MB mp4 端到端通过
      （tag phase4-openclaw-upload-real-analysis-20260610）
- [x] M3 阶段C：知识固化（评估结论：检测/状态/错误等稳定逻辑 M2 已固化为 Bridge 规则，
      无需新建 skill 运行时）。把 5 维度分析框架 + 6 条画面原则按意图注入教练提示词；
      同时修复 Gateway 长生成 30s 超时（改 120s 可配），复拍/脚本等长回复不再 502；
      证据 artifacts/evidence/phase4/openclaw-m3-knowledge-coaching-root-evidence-20260610.json
- [ ] M4 阶段D：端到端测试补充（真实抖音链接全链路 ✓、多视频切换、截图帧展示）与最终证据

交接文档见仓库根目录 HANDOVER.md。
