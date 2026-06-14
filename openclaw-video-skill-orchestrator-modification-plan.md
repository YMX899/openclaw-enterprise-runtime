# OpenClaw Python Skill Orchestrator 改造方案

## 1. 背景与目标

当前 OpenClaw 视频分析 sidecar 的总体流程是：

```text
前端页面
  -> openclaw-bridge
  -> bridge 规则判断 / 创建 job / 拼接 prompt
  -> video-analysis-worker 执行视频分析
  -> openclaw-gateway 生成追问回答
  -> bridge-postgres 保存会话、消息、任务和结果
```

现状中，Bridge 同时承担了 API 边界、状态机、意图识别、知识库注入、视频分析追问 prompt 构造等职责。短期可用，但存在几个问题：

1. Bridge 业务逻辑过重，规则、上下文注入和 prompt 组装混在 `bridge_app.py` / `agent_persona.py` 中。
2. 完整知识库在部分追问场景被重复注入上下文，增加 token 成本和回答漂移风险。
3. 视频分析详细内容 `analysis_detail` 每次追问都可能被重复注入，缺少“一个会话只注入一次”的控制。
4. 当前 skill 主要是设计概念，没有实际 Python 层统一调度模块。
5. 视频分析模型调用仍通过现有 worker/job 执行，但是否触发、如何绑定结果、如何注入上下文，需要统一调度。

本次改造目标是在 **OpenClaw sidecar 内新增 Python 层 skill/orchestrator 模块**，用于统一调度对话、视频任务和上下文策略；同时保持现有总体流程不变，兼容已有历史会话和已有 `video_results`。

目标架构：

```text
前端页面
  -> openclaw-bridge
  -> Python Skill Orchestrator
       - 路由决策
       - 意图识别
       - 知识库选择
       - analysis_detail 注入控制
       - 视频分析 job 调度决策
       - Gateway prompt 构造
  -> video-analysis-worker / openclaw-gateway
  -> bridge-postgres
```

Bridge 继续负责系统边界和持久化；Skill Orchestrator 负责业务调度和上下文策略。

## 2. 不变边界

以下内容保持不变：

1. 前端接口路径不变。
   - `/openclaw-api/chat`
   - `/openclaw-api/jobs`
   - `/openclaw-api/uploads`
   - `/openclaw-api/sessions`
   - `/openclaw-api/sessions/{session_id}/messages`

2. 数据库 schema 不改。
   - 不新增表。
   - 不新增字段。
   - 保持 `bridge_sessions`、`bridge_messages`、`video_jobs`、`video_results` 等现有结构。

3. 视频分析任务仍通过现有 worker/job 执行。
   - Skill 不直接下载视频。
   - Skill 不直接调用 Files API。
   - Skill 不直接请求视频理解模型。
   - Skill 只决定是否创建/等待/绑定现有 `video_jobs`。

4. 历史数据兼容。
   - 兼容只有 `summary`、没有 `analysis_detail` 的历史结果。
   - 兼容已经存在的 `bridge_messages`。
   - 兼容已有 `video_jobs` 和 `video_results`。

5. Bridge 安全职责不下放。
   - 鉴权、用户归属校验、session ownership 校验继续在 Bridge。
   - 上传文件类型和大小校验继续在 Bridge。
   - URL 安全校验继续在 Bridge/worker 保留兜底。

## 3. 新增模块设计

新增模块建议放在：

```text
openclaw-video/src/openclaw_video/orchestrator_skill.py
```

该模块是 Python 层的 skill/orchestrator，不依赖 Gateway 原生 skill runtime。

核心职责：

1. 接收当前 turn 的上下文。
2. 输出结构化调度决策。
3. 选择知识库注入策略。
4. 控制 `analysis_detail` 在一个会话内只长注入一次。
5. 构造最终发给 Gateway agent 的 prompt。
6. 保持可单测、可审计、可逐步替换 Bridge 侧旧逻辑。

### 3.1 核心数据结构

建议定义：

```python
@dataclass(frozen=True)
class OrchestratorInput:
    principal_id: str
    session: BridgeSession
    history: tuple[BridgeMessage, ...]
    user_content: str
    current_video_job_id: str | None
    current_video_status: str | None
    current_video_error_code: str | None
    current_video_result: dict | None
    has_uploaded_or_link_video: bool
    is_video_submission: bool
    is_upload_submission: bool
```

```python
@dataclass(frozen=True)
class OrchestratorDecision:
    route: str
    intent: str
    state: str
    should_create_video_job: bool
    should_call_gateway: bool
    fixed_reply: str | None
    prompt: str | None
    knowledge_mode: str
    knowledge_keys: tuple[str, ...]
    analysis_context_mode: str
    analysis_context_injected: bool
    analysis_context_budget: int
    full_kb_reason: str | None
    debug: dict[str, Any]
```

### 3.2 route 枚举

建议用字符串常量或 `StrEnum`：

```text
fixed_guardrail
fixed_waiting_for_video
fixed_video_analyzing
fixed_error_recovering
create_video_job
answer_initial_video_question
follow_up_opening
follow_up_script
follow_up_picture
follow_up_reshoot
follow_up_why_not_viral
follow_up_general
continue_previous
general_chat
```

这些 route 替代 Bridge 中分散的 if/else 判断，但初期可以先在内部复用现有函数：

```text
detect_intent()
derive_state()
guardrail_for_message()
fixed_state_reply()
error_reply_for()
current_video_from_history()
```

## 4. Bridge 与 Skill 的职责切分

### 4.1 Bridge 保留职责

`bridge_app.py` 继续负责：

1. HTTP 路由。
2. 鉴权和当前用户解析。
3. session ownership 校验。
4. 读取和写入 `bridge_messages`。
5. 创建 `video_jobs`。
6. 查询 `video_results`。
7. 上传文件接收和保存。
8. 调用 Gateway client。
9. 返回 API 响应。

### 4.2 Skill 接管职责

`orchestrator_skill.py` 接管：

1. 当前 turn 的 route 决策。
2. 是否固定回复。
3. 是否调用 Gateway。
4. 知识库注入模式选择。
5. `analysis_detail` 注入策略。
6. prompt 构造。
7. 调试信息输出。

Bridge 调用 skill 的方式：

```python
decision = orchestrator.decide(orchestrator_input)

if decision.fixed_reply:
    write assistant message
    return response

if decision.should_call_gateway:
    gateway.chat(content=decision.prompt)
    write assistant message
    return response
```

## 5. 视频分析模型调用策略

用户要求：视频分析模型调用通过 skill 完成，但采用 A 方案，即 **Skill 只调度现有 worker/job**。

因此定义如下：

```text
Skill 不直接处理视频二进制。
Skill 不直接调用模型。
Skill 决定是否创建 video job。
Bridge 根据 Skill 决策创建 job。
Worker 继续执行真实分析。
Worker 继续保存 summary / analysis_detail。
Skill 在后续回答时读取结果并决定如何注入。
```

### 5.1 链接视频

当前路径：

```text
chat payload 包含 video_url
  -> bridge create_job()
  -> worker 分析
```

改造后：

```text
chat payload 包含 video_url
  -> bridge 构造 OrchestratorInput
  -> skill route = create_video_job
  -> bridge 根据 decision 创建 job
  -> worker 分析
```

### 5.2 上传视频

当前路径：

```text
/uploads
  -> bridge 保存文件
  -> create_job(upload://...)
```

改造后：

```text
/uploads
  -> bridge 完成文件保存和基础校验
  -> skill route = create_video_job
  -> bridge 根据 decision 创建 job
```

上传文件保存仍在 Bridge，因为这属于 HTTP multipart 和文件系统边界，不放入 skill。

### 5.3 视频分析结果

Worker 输出仍保持：

```json
{
  "summary": "...",
  "analysis_detail": "...",
  "signals": {},
  "raw_tool_result": {}
}
```

Skill 读取时使用：

```python
analysis_detail = result.get("analysis_detail") or result.get("summary") or ""
summary = result.get("summary") or ""
```

## 6. analysis_detail 注入策略

用户要求：`analysis_detail` 在一个会话内需要通过提示词注入上下文一次。

由于不允许改数据库 schema，需要使用现有 `bridge_messages` 记录注入状态。

### 6.1 不改 DB 的注入账本方案

在 `bridge_messages` 中写入一条 `system` 或 `tool` 消息作为 marker。

建议使用 `system` role，内容为 JSON 字符串，带固定前缀：

```text
__openclaw_context_marker__{"type":"analysis_detail_injected","job_id":"...","session_id":"...","message_id":"...","created_at":"..."}
```

优点：

1. 不改 schema。
2. 可以按 session 查询现有 messages 判断是否注入过。
3. 可以兼容历史数据，没有 marker 就视为未注入。
4. marker 不展示给用户时，可在 API 序列化或前端渲染层过滤。

注意：当前 `messages()` API 会返回所有消息。如果新增 system marker，必须处理前端展示过滤。

有两种方案：

方案 A：Bridge API 返回时过滤 marker。

```python
def _is_internal_context_marker(message):
    return message.role == "system" and message.content.startswith("__openclaw_context_marker__")
```

`list_messages` 仍返回原始数据，API 序列化前过滤。

方案 B：不用 system 消息，使用 assistant message 中的隐藏标记。

不建议。会污染用户消息内容，也不利于查询。

建议采用方案 A。

### 6.2 注入粒度

按用户确认，粒度是：

```text
一个会话只注入一次长 analysis_detail
```

具体规则：

1. 如果当前 session 没有任何 `analysis_detail_injected` marker，则允许注入较长 detail。
2. 注入后写入 marker。
3. 后续同一 session 的追问不再注入完整 detail，只注入：
   - `summary`
   - 或 intent 裁剪后的 detail 片段
   - 或 “已注入过 detail，请基于会话上下文继续”的简短提示
4. 如果用户在同一 session 分析了新视频：
   - 严格解释“一个会话只注入一次”时，新视频也不再完整注入。
   - 但业务上多视频场景会受影响。

建议优化为：

```text
一个会话内，每个当前视频 job 最多长注入一次。
```

但用户已明确“一个会话”，所以第一版按“session 一次”实现。后续如果多视频追问质量下降，再调整为“session + job_id 一次”。

### 6.3 上下文模式

定义：

```text
detail_once
selected_detail
summary_only
none
```

首次追问：

```text
analysis_context_mode = detail_once
budget = 6000-12000 字符
```

后续追问：

```text
analysis_context_mode = selected_detail 或 summary_only
budget = 1500-4000 字符
```

建议默认预算：

```text
detail_once: 8000 字符
selected_detail: 3000 字符
summary_only: 1500 字符
continue_previous: 3000 字符 detail + 5000 字符 previous assistant
```

## 7. 知识库注入策略

用户要求：完整知识库由 skill 根据问题判断；一般情况下只注入需要的知识库。

### 7.1 知识模式

定义：

```text
none
compact_by_intent
selected_sections
full_kb
```

### 7.2 默认策略

默认不注入完整知识库。

常规追问：

```text
knowledge_mode = compact_by_intent
```

对应现有函数：

```python
knowledge_for_intent(intent)
```

例如：

```text
ask_rewrite_opening -> HOOK_GUIDE
ask_picture_improvement -> PICTURE_PRINCIPLES
ask_reshoot_plan -> PICTURE_PRINCIPLES
ask_why_not_viral -> ANALYSIS_FRAMEWORK
ask_rewrite_script -> ANALYSIS_FRAMEWORK
```

### 7.3 selected_sections

新增知识选择器：

```python
def select_knowledge_sections(user_content: str, intent: str) -> SelectedKnowledge:
    ...
```

第一版可以用规则关键词，不直接用模型判断：

```text
开头 / 前3秒 / 钩子 -> hook_guide
画面 / 镜头 / 场景 / 道具 -> picture_principles
脚本 / 文案 / 口播 -> script_framework
复拍 / 分镜 -> picture_principles + structure_framework
为什么不爆 / 诊断 -> analysis_framework
对标 / 爆款 / 复刻 -> benchmark_framework
```

虽然用户说由 skill 根据问题判断，但建议第一版仍采用 deterministic 规则判断，避免把“是否注入完整知识库”交给 LLM 自由决定。

### 7.4 full_kb 触发条件

完整知识库只在以下场景启用：

1. 用户明确要求：
   - “按完整知识库”
   - “完整方法论”
   - “系统性分析”
   - “从选题到复拍完整拆”
   - “按你们的方法论完整诊断”

2. 用户问题跨多个模块，且不是普通短追问：
   - 同时要求选题、脚本、画面、复拍、转化。
   - 要求完整复盘一条视频。

3. 首次深度诊断，并且用户没有指定单点问题。

4. debug/admin 模式：
   - 未来可加环境变量 `OPENCLAW_FULL_KB_MODE=1`。

### 7.5 full_kb 限制

即使触发 full_kb，也必须设置预算：

```text
full_kb_max_chars = 12000
```

不建议再把 69KB 全量知识库无条件注入。

可先实现简单截断：

```python
full_kb[:12000]
```

后续再升级为章节检索。

## 8. Prompt 构造策略

将现有 `build_agent_message()`、`build_branch_prompt()`、`build_continue_prompt()` 逐步迁移到 skill 内部。

建议新增：

```python
class PromptBuilder:
    def build(self, decision: OrchestratorDecision, context: PromptContext) -> str:
        ...
```

### 8.1 PromptContext

```python
@dataclass(frozen=True)
class PromptContext:
    system_persona: str
    markdown_rules: str
    state_hint: str
    branch_instruction: str | None
    user_content: str
    knowledge_text: str
    analysis_text: str
    previous_assistant: str | None
```

### 8.2 Prompt 顺序

建议统一顺序：

```text
1. SYSTEM_PERSONA
2. MARKDOWN_OUTPUT_RULES
3. 当前状态提示
4. 本轮 route / 分支要求
5. 视频真实分析上下文
6. 相关知识块
7. 上一条回复（仅 continue）
8. 用户消息
```

把视频上下文放在知识库前面，原因是回答必须优先基于真实视频，知识库只作为方法论辅助。

当前代码中知识库在视频分析结果前面，建议改掉。

## 9. Bridge 改造步骤

### 9.1 新增 `orchestrator_skill.py`

实现：

```text
OrchestratorInput
OrchestratorDecision
SkillOrchestrator
PromptBuilder
KnowledgeSelector
AnalysisContextSelector
ContextMarker
```

第一版内部可以复用现有 `agent_persona.py` 的常量和函数，避免一次性大重构。

### 9.2 改造 `/chat`

当前 `/chat` 的逻辑较长，应拆为：

```python
principal = await current_principal(request)
session = session_store.get_session(...)
history = session_store.list_messages(...)
user_message = session_store.add_message(...)
context = build_orchestrator_input(...)
decision = orchestrator.decide(context)
```

然后按 decision 执行：

```python
if decision.fixed_reply:
    write assistant
    return

if decision.should_call_gateway:
    result = await gateway.chat(prompt=decision.prompt)
    write assistant
    maybe_write_context_marker(decision)
    return
```

### 9.3 改造视频提交带问题场景

当前 `_answer_video_submission_question()` 中直接：

```python
build_branch_prompt(..., knowledge_context=load_full_knowledge_context())
```

改为：

```python
decision = orchestrator.decide_initial_video_question(...)
gateway.chat(decision.prompt)
```

并遵守：

```text
不默认注入完整知识库
analysis_detail 按 session marker 控制
```

### 9.4 消息返回过滤 internal marker

修改 `_serialize_message` 或 messages endpoint。

建议不要在 `_serialize_message` 内隐藏，因为其他内部调用可能需要 marker。

新增：

```python
def _visible_messages(messages):
    return [item for item in messages if not is_internal_context_marker(item)]
```

在这些 API 中过滤：

```text
GET /sessions/{session_id}/messages
list sessions preview 相关逻辑如有使用 messages，也应过滤
```

内部状态判断仍使用未过滤 history。

## 10. agent_persona.py 改造策略

短期：

1. 保留现有常量。
2. 保留 `detect_intent()`、`derive_state()`、`guardrail_for_message()`。
3. 保留 `knowledge_for_intent()`。
4. 将 `build_branch_prompt()` / `build_continue_prompt()` 标记为 legacy，暂时不删。
5. 新逻辑从 `orchestrator_skill.py` 调用常量和底层规则。

中期：

1. 将 prompt builder 迁出 `agent_persona.py`。
2. `agent_persona.py` 只保留 persona、intent、state、固定回复。
3. 上下文选择和知识选择全部归 `orchestrator_skill.py`。

## 11. AGENT.md 修改建议

`AGENT.md` 需要同步更新，不再描述为“Bridge 注入完整上下文”，而是描述：

```text
Bridge 接收请求并完成安全与持久化。
Python Skill Orchestrator 负责调度、知识选择、视频上下文裁剪和 prompt 构造。
Gateway agent 只负责基于已注入上下文生成自然语言回答。
```

建议修改第 5 节“工具与消息路由”：

```markdown
Bridge 侧负责鉴权、会话、任务和安全边界。
Python Skill Orchestrator 负责对话路由、知识选择和上下文注入。
Gateway agent 不直接调用视频解析工具，也不直接读取文件。
视频分析仍由 video-analysis-worker 处理，skill 只调度 job 和使用分析结果。
```

## 12. 兼容策略

### 12.1 历史 video_results

读取逻辑：

```python
summary = result.get("summary") or ""
analysis_detail = result.get("analysis_detail") or summary
```

如果没有 `analysis_detail`，仍可追问。

### 12.2 历史会话

历史会话没有 context marker。

第一次在旧会话中追问时：

```text
视为未注入过 detail
允许 detail_once
写入 marker
```

### 12.3 前端兼容

前端不应看到 marker。

如果前端直接渲染 `role=system`，必须由 API 层过滤。

### 12.4 Gateway session 兼容

Gateway 可能已有自己的 session memory。

Skill 仍以 bridge-postgres 为准，不依赖 Gateway 是否记住上文。

## 13. 测试方案

### 13.1 单元测试

新增：

```text
tests/test_orchestrator_skill.py
```

覆盖：

1. 普通新会话：
   - route = general_chat 或 fixed waiting reply。

2. 不支持平台：
   - route = fixed_guardrail
   - should_call_gateway = False

3. 视频分析中：
   - route = fixed_video_analyzing

4. 分析失败：
   - route = fixed_error_recovering

5. 已分析视频首次追问：
   - analysis_context_mode = detail_once
   - analysis_context_injected = True
   - knowledge_mode != full_kb unless触发条件满足

6. 已分析视频第二次追问：
   - 根据 marker 判断
   - analysis_context_mode = selected_detail 或 summary_only
   - 不再 detail_once

7. 完整知识库触发：
   - 用户说“按完整方法论完整诊断”
   - knowledge_mode = full_kb
   - full_kb_reason 非空

8. 普通开头改法：
   - knowledge_mode = compact_by_intent
   - knowledge_keys 包含 hook_guide

9. 继续：
   - route = continue_previous
   - previous_assistant 被裁剪
   - 不默认 full_kb

10. 历史 result 无 `analysis_detail`：
   - fallback 到 summary

### 13.2 Bridge 集成测试

扩展：

```text
tests/test_bridge_app.py
```

覆盖：

1. marker 不返回给 `/messages`。
2. 首次追问后写入 marker。
3. 二次追问不再写入重复 marker。
4. 固定回复不写 marker。
5. create job 路径保持原返回契约。

### 13.3 Prompt 预算测试

新增断言：

```text
full_kb 不超过配置字符数
analysis_detail 不超过 detail_once 预算
selected_detail 不超过 selected budget
previous_assistant 不超过 continuation budget
```

### 13.4 端到端验收

在 root 环境验证：

1. 新会话上传视频，分析完成。
2. 第一次问“开头怎么改”，detail 注入一次。
3. 第二次问“脚本怎么改”，不重复完整 detail。
4. 问“按完整方法论完整诊断”，触发 full_kb。
5. 问“继续”，不重新塞完整知识库和完整 detail。
6. 查询 `/messages`，用户不可见 marker。
7. 历史会话追问仍正常。

## 14. 配置项建议

新增环境变量，全部可选：

```text
OPENCLAW_ORCHESTRATOR_SKILL_ENABLED=1
OPENCLAW_FULL_KB_MAX_CHARS=12000
OPENCLAW_DETAIL_ONCE_MAX_CHARS=8000
OPENCLAW_SELECTED_DETAIL_MAX_CHARS=3000
OPENCLAW_SUMMARY_CONTEXT_MAX_CHARS=1500
OPENCLAW_PREVIOUS_ASSISTANT_MAX_CHARS=5000
OPENCLAW_FULL_KB_MODE=auto
```

`OPENCLAW_FULL_KB_MODE` 可选：

```text
off   -> 永不注入完整知识库
auto  -> skill 根据问题判断
on    -> 调试模式，允许更多 full_kb
```

默认：

```text
OPENCLAW_ORCHESTRATOR_SKILL_ENABLED=1
OPENCLAW_FULL_KB_MODE=auto
```

为降低发布风险，可以支持关闭：

```text
OPENCLAW_ORCHESTRATOR_SKILL_ENABLED=0
```

关闭后走旧逻辑。

## 15. 发布策略

建议分三步发布。

### 阶段 1：旁路实现，不改变行为

1. 新增 `orchestrator_skill.py`。
2. 单元测试覆盖 route decision。
3. Bridge 暂不使用新 skill，或只在 debug 下调用并记录 decision。
4. 对比旧逻辑和新 decision。

### 阶段 2：启用 skill，但保留旧逻辑开关

1. `/chat` 改为使用 skill。
2. 保留 `OPENCLAW_ORCHESTRATOR_SKILL_ENABLED=0` 回滚。
3. root 端到端验证。

### 阶段 3：迁移视频提交带问题场景

1. `_answer_video_submission_question()` 改为 skill prompt。
2. 完整清理旧的 full knowledge 默认注入。
3. 增加证据文件。

## 16. 主要风险与处理

### 16.1 marker 污染前端

风险：system marker 被前端展示。

处理：

1. API 层过滤 marker。
2. 测试覆盖 `/messages` 不返回 marker。

### 16.2 一个会话只注入一次 detail 导致多视频追问信息不足

风险：同一 session 分析第二条视频后，不能完整注入第二条视频 detail。

处理：

第一版按用户要求实现“session 一次”。同时在 debug 中记录：

```text
analysis_context_mode=summary_only
reason=session_detail_already_injected
```

后续如质量下降，改为“session + job_id 一次”。

### 16.3 skill 判断 full_kb 不稳定

风险：如果用 LLM 判断 full_kb，会不可控。

处理：

第一版 skill 用规则判断，不调用 LLM 判断 full_kb。

### 16.4 Prompt 过长

风险：full_kb + detail + previous assistant 叠加。

处理：

所有上下文都有字符预算，并在测试中断言。

### 16.5 旧逻辑回滚

风险：新 skill 上线后影响正常对话。

处理：

保留环境变量：

```text
OPENCLAW_ORCHESTRATOR_SKILL_ENABLED=0
```

可快速回滚到旧 Bridge 逻辑。

## 17. 文件修改清单

新增：

```text
openclaw-video/src/openclaw_video/orchestrator_skill.py
openclaw-video/tests/test_orchestrator_skill.py
```

修改：

```text
openclaw-video/src/openclaw_video/bridge_app.py
openclaw-video/src/openclaw_video/agent_persona.py
openclaw-video/openclaw/agents/main/AGENT.md
openclaw-video/tests/test_bridge_app.py
openclaw-video/tests/test_agent_persona.py
```

可选修改：

```text
openclaw-video/schemas/message-list-response.schema.json
```

如果 marker 被 API 层过滤，对外 schema 不需要变化。

## 18. 验收标准

功能验收：

1. 视频链接分析流程不变。
2. 上传视频分析流程不变。
3. 用户追问仍能基于 `summary` / `analysis_detail` 回答。
4. 历史会话可继续追问。
5. 不支持平台、主页链接、解析失败仍固定回复。
6. 普通聊天仍可引导用户发视频。

上下文验收：

1. 普通追问不注入完整知识库。
2. 只有触发条件满足时才注入完整知识库。
3. 一个会话只进行一次 `detail_once` 长注入。
4. 后续追问使用 selected detail 或 summary。
5. `continue` 不重复完整知识库和完整 detail。

工程验收：

1. 新 skill route decision 可单测。
2. prompt 长度有预算控制。
3. marker 不对用户可见。
4. 可通过环境变量关闭新 orchestrator。
5. root 端到端证据保存到：

```text
artifacts/evidence/phase4/
```

## 19. 推荐最终实现原则

本次改造不要追求“让 agent 自动选择 skill”。更可靠的方式是：

```text
Python Skill Orchestrator 输出结构化 decision；
Bridge 只执行 decision；
Gateway agent 只负责自然语言生成。
```

这样能同时满足：

1. 总体流程保持现状。
2. Bridge 逻辑变薄。
3. 上下文注入可控。
4. 知识库不再重复全量进入 prompt。
5. 视频分析仍走稳定 worker。
6. 历史数据兼容。
7. 后续可以逐步升级为真正 Gateway skill 或工具调用机制。
