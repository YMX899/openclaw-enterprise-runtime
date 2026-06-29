# OpenClaw Enterprise Runtime ⚡

<p align="center">
  <strong>High-concurrency, user-scoped agent runtime built on top of OpenClaw.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/runtime-Node%2024-3C873A" alt="Node 24">
  <img src="https://img.shields.io/badge/agents-1000%20concurrent-success" alt="1000 concurrent agents">
  <img src="https://img.shields.io/badge/status-runtime%20fork-orange" alt="Runtime fork">
</p>

<p align="center">
  <img src="docs/assets/openclaw-enterprise-runtime-hero.png" alt="OpenClaw Enterprise Runtime 1000 concurrent agents" width="960">
</p>

<p align="center">
  <a href="#中文">中文</a> ·
  <a href="#english">English</a> ·
  <a href="#quick-start--快速开始">Quick Start</a> ·
  <a href="#architecture--架构">Architecture</a>
</p>

---

<a id="中文"></a>

## 中文 🇨🇳

**OpenClaw Enterprise Runtime** 是一个面向高并发 agent 产品的 OpenClaw runtime 改造版。

这个项目的出发点很朴素：现在不缺能跑 demo 的 agent 框架，但真正面向商业用户时，能把用户隔离、临时 workspace、session log、模型 key 池和 1000 级并发自然串起来的选择并不多。

所以我们基于 OpenClaw 做了这个 runtime fork。它不是另一个聊天壳子，也不是把业务硬塞进一个大 prompt。它解决的是更底层的问题：当很多用户同时发起任务时，系统怎样动态组合用户上下文、临时 workspace、session log、模型 key 和 agent runtime，然后稳定地跑起来。

这个仓库当前重点在三件事：

- 把 OpenClaw 的 agent / subagent 默认并发提升到 1000。
- 增加大模型 API key 请求池，遇到 rate limit 自动切换可用 key。
- 提供可重复的压力测试脚本，确认 runtime 能同时触发 1000 个 agent 模型请求。
- 提供 `enterprise.runtime.run`，让上游产品服务显式传入用户 workspace、OpenClaw session key、runtime config、附件和运行目录。

项目目标很明确：让开发者能在 OpenClaw 的执行能力上，搭一个真正面向大众用户的 agent 系统。

## 为什么做这个 🧭

OpenClaw 原本很适合个人助理和多渠道 agent，但商业级 agent 产品还有几层额外需求：

用户上下文来自数据库，workspace 是临时创建的，session log 要能归档和回放，模型 key 会被限流，任务可能同时来上千个。

所以我们把系统拆成两类空间：

```text
Meta Workspace
  负责模板、用户上下文、权限、模型路由、运行索引

Runtime Workspace
  某一次 agent run 真正工作的临时目录
```

临时 workspace 本身不难，难的是要有一个元工作区持续管理它们。每次请求到来时，系统从数据库和模板里编译出一份固定的 `RunSpec`，然后交给 OpenClaw runtime 执行。

<a id="architecture--架构"></a>

## Architecture / 架构 🏗️

```text
User Request
  -> Agent Compiler
       - load user profile / memory / permissions from DB
       - choose agent template
       - build immutable RunSpec
  -> Meta Workspace
       - register runId / sessionKey / workspace path
       - keep trace and cleanup metadata
  -> Model Broker
       - choose provider / model / api key
       - skip cooled-down keys
       - mark rate-limited keys
  -> OpenClaw Runtime Adapter
       - translate RunSpec to OpenClaw config/session/runtime params
       - start the agent run
  -> Runtime Workspace
       - files, scratch data, artifacts, session log
  -> Result Writer
       - save output, usage, trace, memory delta
```

关键边界是 `RunSpec`。

`RunSpec` 会在 runtime 启动前冻结这次请求的动态配置。这样每次运行都更容易复现、排查，也更适合并发场景。

```ts
type RunSpec = {
  runId: string;
  userId: string;
  agentTemplateId: string;
  sessionKey: string;
  workspaceDir: string;
  model: string;
  systemPrompt: string;
  userPrompt: string;
  tools: string[];
  permissions: Record<string, unknown>;
  memorySnapshot: string;
};
```

## 当前实现状态 ✅

runtime 底座已经改完，并通过了本地压力验证。

```text
Subagent lane stress:
  requested=1000
  peakActive=1000

Gateway mock stress:
  agents=1000
  finalOk=1000
  modelRequests=1000
  modelPeakActive=1000

API key pool mock:
  agents=20
  finalOk=20
  modelStatuses={"200":20,"429":10}
```

这说明 OpenClaw runtime 已经可以同时把 1000 个 agent 推到模型请求层。真实 provider 是否全部成功，取决于上游账号、模型、RPM/TPM、并发额度和 key 池配置。

`enterprise.runtime.run` 当前已经支持真实 workspace 直跑、OpenClaw 原生 session 续写、file session/artifact store、workspace queue、session lock、附件校验、模型 input 能力检查、API key pool、hard timeout、stalled-run guard 和 detached key lease 延迟释放。详细契约见 [Enterprise runtime](docs/enterprise-runtime.md)。

2026-06-29 真实服务器上线前测试证明主链路可跑通，但还不是最终生产放行版本。上线前 P0：

```text
RuntimeConfig.limits.maxToolCalls 已定义，但 live agent loop 尚未强制执行。
resolveRuntimeDirs 在拒绝 workspace 内 state/log/tmp 前会先创建目录，需要改成先校验后 mkdir。
```

图片链路验收拆成两部分：runtime 负责附件在 workspace 内、MIME/魔数/大小/数量校验、传给模型和返回 usage；模型把图片中的文字读对属于模型能力验收。MiMo v2.5 在真实 smoke 中看到图片，但曾把 `HUO7403` 读成 `HU07403`。

## 设计理念 ✨

### 1. Agent 是模板，不是状态容器

同一个 agent 定义可以服务很多用户，但每个用户请求都必须有自己的 run state、session log 和 workspace。

### 2. 动态组合，但运行前冻结

用户记忆、权限、工具和模型都可以动态选择。真正执行前，它们会被编译成一份不可变的 `RunSpec`。运行过程中不要偷偷改配置，这样排查问题会简单很多。

### 3. Runtime 只负责执行

OpenClaw runtime 不应该知道你的业务数据库怎么设计。业务系统负责生成 `RunSpec`，runtime adapter 负责把它翻译成 OpenClaw 能执行的参数。

### 4. 并发靠隔离和调度，不靠一个超大 loop

1000 并发不是一个 loop 处理 1000 个用户，而是同一个 agent 模板派生出 1000 个独立 run。Node 的异步 I/O 很适合这个模型。

### 5. Model key 是资源，也需要调度

模型 key 会限流。当前实现提供进程内 key pool：健康 key 轮询使用，命中 `429` / `rate_limit` 后进入冷却，后续请求自动跳过。

<a id="quick-start--快速开始"></a>

## Quick Start / 快速开始 🚀

### 1. Clone

```bash
git clone git@github.com:YMX899/openclaw-enterprise-runtime.git
cd openclaw-enterprise-runtime
```

### 2. Use Node 24

```bash
node -v
# recommended: v24.x
```

如果本机还没有 Node，建议用你习惯的版本管理器安装 Node 24。

### 3. Install dependencies

这个 fork 沿用 OpenClaw 上游 workspace。干净环境里直接安装依赖：

```bash
corepack enable
pnpm install
```

### 4. Configure model keys

单 key：

```bash
export OPENAI_API_KEY="sk-..."
```

多 key 轮换：

```bash
export OPENAI_API_KEYS="sk-key-1,sk-key-2,sk-key-3"
export OPENCLAW_API_KEY_POOL_RATE_LIMIT_COOLDOWN_MS=60000
```

自定义 provider id 也沿用同样的规则：

```bash
export HAPPYAI_API_KEYS="key-a,key-b,key-c"
```

### 5. Run the stress checks

lane 级并发：

```bash
npx --no-install tsx scripts/stress/subagent-lane-concurrency.ts
```

gateway 级 1000 agent mock：

```bash
OPENCLAW_STRESS_AGENTS=1000 \
OPENCLAW_STRESS_RESPONSE_DELAY_MS=30000 \
OPENCLAW_STRESS_REQUEST_TIMEOUT_MS=240000 \
node --import tsx scripts/stress/gateway-agent-concurrency.ts
```

API key pool 行为：

```bash
OPENCLAW_STRESS_AGENTS=20 \
OPENCLAW_STRESS_RESPONSE_DELAY_MS=1000 \
OPENCLAW_STRESS_REQUEST_TIMEOUT_MS=120000 \
OPENCLAW_STRESS_RATE_LIMIT_BEARER_TOKENS=stress-test \
STRESS_OPENAI_API_KEYS=stress-test,stress-backup \
node --import tsx scripts/stress/gateway-agent-concurrency.ts
```

预期 key-pool 结果：

```json
{
  "ok": true,
  "agents": 20,
  "finalOk": 20,
  "modelStatuses": {
    "200": 20,
    "429": 10
  }
}
```

OpenAI-compatible 真实上游 smoke test：

```bash
OPENCLAW_STRESS_UPSTREAM_BASE_URL="https://your-provider.example/v1" \
OPENCLAW_STRESS_UPSTREAM_API_KEY_ENV=YOUR_PROVIDER_API_KEY \
OPENCLAW_STRESS_MODEL="your-cheapest-working-model" \
OPENCLAW_STRESS_AGENTS=1000 \
OPENCLAW_STRESS_REQUEST_TIMEOUT_MS=240000 \
node --import tsx scripts/stress/gateway-agent-concurrency.ts
```

真实上游测试建议先从小并发开始，再逐步放大。runtime 能发起这些并发运行，但 provider 账号仍然需要足够的 RPM、TPM 和连接容量。

## Using it as a framework / 作为框架使用 🧩

理想的开发者入口应该保持很小：

```ts
const system = createAgentSystem({
  metaWorkspace,
  modelBroker,
  runtime: openClawRuntime(),
});

const result = await system.run({
  userId: "u_123",
  template: "researcher",
  input: "Analyze this project and return an action plan.",
});
```

框架内部处理这些重复但关键的工作：

```text
load user context
compile RunSpec
create runtime workspace
select provider/model/key
run OpenClaw
write trace/session/usage
clean up temporary files
```

这就是这个 fork 的定位：开发者不需要理解每个 OpenClaw 配置字段，也能安全地跑用户级 agent。

## Runtime changes / Runtime 改造点 🔧

### Concurrency limits / 并发上限

默认 agent 和 subagent 并发上限提升到 1000。

```text
DEFAULT_AGENT_MAX_CONCURRENT=1000
DEFAULT_SUBAGENT_MAX_CONCURRENT=1000
DEFAULT_SUBAGENT_MAX_CHILDREN_PER_AGENT=1000
```

### API key pool

runtime 现在有一个共享的进程内 key pool。

```text
healthy key -> selected round-robin
rate-limited key -> cooldown
next request -> skip cooled-down key
same run -> retry with another healthy key
```

这个实现故意保持简单，适合单 gateway 进程。多进程生产部署时，建议把冷却状态和额度窗口迁到 Redis 或独立 broker。

### Stress tooling / 压测工具

仓库里包含两个压测脚本：

```text
scripts/stress/subagent-lane-concurrency.ts
scripts/stress/gateway-agent-concurrency.ts
```

gateway 脚本可以跑本地 mock、真实 OpenAI-compatible 上游代理，也可以模拟 rate limit。

## Production notes / 生产建议 🧱

如果要做公开 agent 平台，建议在 runtime 前面放一个真正的 `ModelBroker`。

它应该负责：

- provider and model routing
- per-key concurrency limits
- RPM / TPM windows
- `Retry-After` parsing
- Redis-backed cooldown state
- usage accounting
- circuit breaking

当前 key pool 适合作为 runtime fallback。多 worker 部署时，它不应该是唯一的模型控制平面。

## Repository layout / 目录 🗂️

```text
src/agents/api-key-rotation.ts
  共享 API key pool 和限流轮换逻辑。

src/agents/embedded-agent-runner/run/auth-controller.ts
  runtime 鉴权选择，以及同一次 run 内的 key 切换。

src/agents/embedded-agent-runner/run.ts
  agent run loop 集成点。

src/config/agent-limits.ts
  默认并发上限。

scripts/stress/
  可重复的并发和 key-pool 压测。
```

## Roadmap 🛠️

- 补齐面向数据库用户上下文的 `AgentCompiler`。
- 增加一等公民级别的 `RunSpec` schema。
- 实现带 run/session 索引的 `MetaWorkspace`。
- 把进程内 key pool 升级成 Redis-backed `ModelBroker`。
- 提供 SDK，让开发者不直接碰 OpenClaw 原始配置也能跑用户级 agent。
- 增加临时 runtime workspace 的清理和归档策略。

---

<a id="english"></a>

## English 🇺🇸

**OpenClaw Enterprise Runtime** is an independent runtime fork of OpenClaw for high-concurrency agent products.

It exists because many agent frameworks are good enough for demos, but become awkward once a commercial product needs user isolation, temporary workspaces, session logs, API key routing, and 1000-level concurrency.

The core idea is simple: an agent product should dynamically assemble the user context, workspace, session log, model route, API key, and tool policy for each request, then hand a frozen run spec to the runtime.

OpenClaw remains the execution engine. This fork adds the pieces needed to make that engine easier to use under load.

## What is different?

- Default agent and subagent concurrency are raised to 1000.
- Main model calls can use a shared API key pool.
- Rate-limited keys are cooled down and skipped.
- Stress tests verify 1000 concurrent agent runs at the gateway/model boundary.
- `enterprise.runtime.run` disables child-agent/subagent and cross-session orchestration tools at the service boundary.
- The architecture is designed around meta workspaces and temporary runtime workspaces.

## The mental model

A user request does not create a permanent agent. It creates a run.

```text
Agent Template + User Context + Permissions + Memory + Model Route
  -> RunSpec
  -> temporary workspace
  -> OpenClaw runtime
  -> result + trace + usage
```

This keeps the developer API clean and keeps the runtime honest. Each run is isolated, traceable, and reproducible.

## Design principles

- Compile dynamic context into a `RunSpec` before the runtime starts.
- Keep OpenClaw focused on execution, not business database concerns.
- Treat API keys as schedulable resources, because rate limits are part of production.
- Scale with isolated runs and async I/O, not one giant loop.

## How to use it

Clone the repo, install with `pnpm install`, configure `OPENAI_API_KEY` or `OPENAI_API_KEYS`, then run the stress scripts under `scripts/stress/`.

For a product integration, place your own `AgentCompiler`, `MetaWorkspace`, and `ModelBroker` in front of the OpenClaw runtime adapter. The runtime receives a frozen run spec and returns output, trace, usage, and workspace artifacts.

## Verified behavior

Local stress tests have confirmed:

```text
1000 subagent lane tasks active at once
1000 gateway agent runs completed
1000 model requests active at the same time
API key fallback after mocked 429 responses
```

Live providers can still rate limit you. This runtime can fan out 1000 requests; it cannot make an upstream provider accept them without enough quota.

## Upstream / 致谢

This project is an independent runtime fork of [OpenClaw](https://github.com/openclaw/openclaw).
OpenClaw provides the original agent runtime, gateway, and workspace foundation. This fork focuses on high-concurrency orchestration, API key routing, and enterprise-style runtime isolation.

本项目基于 OpenClaw 改造而来。感谢 OpenClaw 原项目提供的 agent runtime、gateway 和 workspace 基础能力。当前 fork 主要聚焦商业并发、模型 key 池、临时 workspace 和企业级 runtime 隔离。

## License

MIT. This project is based on OpenClaw and keeps the same license model.
