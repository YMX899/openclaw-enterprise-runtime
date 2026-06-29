---
summary: "Enterprise runtime contract, isolation model, model routing, stores, and prelaunch validation status"
title: "Enterprise runtime"
read_when:
  - Calling enterprise.runtime.run from an upstream product service
  - Configuring user workspaces, sessions, model profiles, key pools, and runtime stores
  - Auditing prelaunch runtime readiness
---

# Enterprise runtime

`enterprise.runtime.run` runs one product request against one real user workspace. The upstream product service prepares the workspace path, OpenClaw session key, runtime config id, model/tool/plugin overrides, runtime directories, user message, and attachments. The runtime validates and freezes those inputs, translates them into OpenClaw runtime parameters, runs the native agent loop, and returns a `RuntimeRunResult`.

The runtime does not resolve product users, permissions, memories, billing, or database records. Those belong to the upstream system. This module consumes the prepared run spec and enforces the runtime boundary.

## Run chain

```text
RuntimeRunSpec
  -> enterprise.runtime.run
  -> validate protocol
  -> resolve workspace realpath
  -> resolve runtimeConfigId and model profile
  -> freeze ResolvedRuntimeConfigSnapshot
  -> resolve state/log/tmp dirs
  -> resolve attachments
  -> check model input capability
  -> acquire workspace queue
  -> acquire session lock
  -> acquire model key lease
  -> build per-run OpenClaw config
  -> run OpenClaw native agent loop
  -> write OpenClaw native session transcript
  -> write runtime events/result
  -> return RuntimeRunResult
```

## RuntimeRunSpec

```ts
type RuntimeRunSpec = {
  runId: string;
  tenantId: string;
  userId: string;
  workspaceId: string;
  threadId: string;
  runtimeConfigId: string;
  runtimeConfigVersion?: string;

  workspace: {
    realPath: string;
    accessMode: "read" | "write";
  };

  productSession: {
    threadId: string;
    openclawSessionKey: string;
    metadata?: Record<string, unknown>;
  };

  modelOverride?: RuntimeModelOverride;

  tools?: {
    profileId?: string;
    allow?: string[];
    deny?: string[];
  };

  plugins?: {
    enabled?: string[];
    disabled?: string[];
  };

  runtime?: {
    stateDir?: string;
    configPath?: string;
    logsDir?: string;
    tmpRoot?: string;
  };

  input: {
    message: string;
    attachments?: Array<{
      name: string;
      path: string;
      kind?: string;
    }>;
  };
};
```

`workspace.realPath` is the only workspace root for this run. Attachments must be inside it. `stateDir`, `logsDir`, and `tmpRoot` must not be inside it.

`productSession.openclawSessionKey` is passed through as the OpenClaw native session key. `runtimeConfigId` selects model, tools, plugins, limits, compaction, and key-pool policy, but it is not part of the session key and is not used as an OpenClaw agent id.

## Stores and paths

The current implementation supports file stores:

```text
RuntimeConfig.sessionStoreId -> sessionStores[type=file].rootDir -> stateDir
RuntimeConfig.artifactStoreId -> artifactStores[type=file].logsDir -> logsDir
RuntimeConfig.artifactStoreId -> artifactStores[type=file].tmpRoot -> tmpRoot
```

OpenClaw session state is stored under:

```text
<stateDir>/agents/enterprise-runtime/sessions/sessions.json
<stateDir>/agents/enterprise-runtime/sessions/<sessionId>.jsonl
```

Runtime artifacts are stored under:

```text
<logsDir>/runs/<runId>/events.jsonl
<logsDir>/runs/<runId>/result.json
<logsDir>/runs/<runId>/error.json
<stateDir>/enterprise-runtime/config-snapshots/<runId>.json
```

`sessionStores[type=database]`, `sessionStores[type=db-object]`, and `artifactStores[type=object]` are future store-adapter shapes. They currently fail closed rather than silently falling back to default OpenClaw directories.

## Isolation and concurrency

The current runtime modifies the real workspace directly. Overlay workspaces, layer materialization, and diff writeback are not part of this implementation.

Workspace and session isolation:

```text
same workspace -> FIFO queue
same openclawSessionKey -> session lock
different workspace -> can run concurrently
workspace external read/write -> blocked by tool boundary
tools.deny -> deny wins over allow
read accessMode -> mutating tools hidden
shell/process without sandbox -> fail closed
```

The queue, session lock, stalled-run guard, and key lease are in-process mechanisms. Multi-instance deployment must replace them with Redis, database, or another distributed coordination layer.

## Timeout and stalled runs

`limits.maxRunSeconds` starts after a run becomes active. The handler wraps `runEnterpriseAgent` with hard timeout behavior. If the abort signal fires and the agent loop does not settle, the API still returns `status = "timeout"`.

When a timeout response is detached from an unsettled agent loop:

```text
workspace/session are marked stalled
same workspace/session requests return RUNTIME_RUN_STALLED
the model key lease remains held
the key lease is released only after the detached agent loop settles
the key is cooled down as overloaded
the stalled marker is cleared after the detached task settles
```

This keeps the API from hanging while preventing overlapping writes and premature API-key reuse.

## Model profiles and API key pools

A model profile describes provider, model id, OpenAI-compatible API mode, thinking/reasoning fields, input capabilities, timeout, max tokens, and auth pool id.

For Xiaomi MiMo multimodal runtime use:

```json5
{
  provider: "xiaomimimo",
  model: "mimo-v2.5",
  api: "openai-completions",
  baseUrl: "https://api.xiaomimimo.com/v1",
  authPoolId: "mimo-prod-main",
  input: ["text", "image"],
  thinking: "off",
  reasoning: "off",
  maxTokens: 4096,
}
```

MiMo v2.5 rejects non-`off` thinking settings. Runtime config should not send `thinking: "medium"` or other unsupported values to that profile.

The key broker is in-process. It leases keys by pool, respects `maxConcurrent`, skips cooled-down keys, and classifies rate-limit/quota/auth/overload failures.

## Attachments and images

Image-capable product requests should use `input: ["text", "image"]` on the resolved model profile. This is a capability declaration, not a requirement that every request includes an image.

Runtime validates:

```text
attachment path is inside workspace
file exists and is a regular file
MIME/kind is supported
image magic bytes match PNG/JPEG/WEBP/GIF
single image <= 10 MB
single request <= 10 images
model input includes image when image attachments exist
```

Runtime attachment acceptance and model visual accuracy are separate checks. The runtime can prove that an image was accepted, converted, and sent to the model through `usage.input` and `usage.attachmentCount`. Whether the model reads text in the image correctly is a model-quality check. In the 2026-06-29 prelaunch smoke, MiMo saw the image but read `HUO7403` as `HU07403`; that is not a runtime transport failure.

## Current prelaunch status

The 2026-06-29 real-server prelaunch test covered:

```text
real Gateway WebSocket RPC enterprise.runtime.run
real Xiaomi MiMo API
five user workspaces
ten concurrent runtime requests
workspace queue and session lock
native OpenClaw session continuation
temporary product message database append
workspace reads and writes
image attachment success path
text-only profile image rejection
invalid/empty/MIME mismatch/oversized/11-image rejection
workspace external attachment rejection
symlink attachment escape rejection
relative/absolute read/write escape rejection
tools.deny write
read accessMode
shell/process fail-closed without sandbox
sessionStoreId/artifactStoreId directory resolution
state/log/tmp outside user workspace in the normal path
service health/ready after test
secret cleanup and scan
```

The main runtime path works, but this version should not be treated as a final production pass until these P0 items are fixed:

```text
P0: RuntimeConfig.limits.maxToolCalls is defined but not yet enforced by the live agent loop.
P0: resolveRuntimeDirs currently creates state/log/tmp directories before rejecting workspace-internal paths.
```

Additional prelaunch clarifications:

```text
Concurrency SLA is per workspace serial, cross workspace concurrent.
Five workspaces with two runs each can peak at five active runs; ten active runs require ten distinct workspaces or users.
Runtime session/log canary scans must assign owner by sessionKey, workspaceDir, or runId before flagging leaks.
Gateway status/capability discovery does not yet expose enterprise.runtime.run even though the RPC works.
Tool-loop and timeout pressure can temporarily degrade event-loop ready diagnostics.
```

## Verification commands

```bash
node scripts/run-tsgo.mjs -p tsconfig.core.json --incremental false
OPENCLAW_BUILD_ALL_NO_PNPM=1 node scripts/build-all.mjs qaRuntime
```

Focused test commands used during development:

```bash
corepack pnpm vitest run \
  src/enterprise-runtime/paths.test.ts \
  src/enterprise-runtime/attachments.test.ts \
  src/enterprise-runtime/session-store.test.ts \
  src/enterprise-runtime/workspace-queue.test.ts \
  src/enterprise-runtime/session-lock.test.ts \
  src/enterprise-runtime/model-broker/broker.test.ts \
  src/enterprise-runtime/config/resolve-snapshot.test.ts \
  src/enterprise-runtime/config/run-config.test.ts

corepack pnpm vitest run \
  packages/gateway-protocol/src/schema/enterprise-runtime.test.ts \
  src/gateway/server-methods/enterprise-runtime.test.ts \
  src/gateway/server-methods/enterprise-runtime.huahuoai-testbench.test.ts
```

After adding the detached key-lease regression, Vitest on the Windows workstation repeatedly stalled in rolldown plugin prebuild before producing test output. The final deployment was verified with typecheck, build, dist grep, and live server health/ready checks.
