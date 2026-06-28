import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuntimeRunSpec } from "../../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { ENTERPRISE_RUNTIME_METHOD } from "../../enterprise-runtime/constants.js";
import { testing as brokerTesting } from "../../enterprise-runtime/model-broker/broker.js";

const mocks = vi.hoisted(() => ({
  runEnterpriseAgent: vi.fn(),
  getRuntimeConfig: vi.fn(),
}));

vi.mock("../../config/io.js", () => ({
  getRuntimeConfig: mocks.getRuntimeConfig,
}));

vi.mock("../../enterprise-runtime/agent-runner.js", () => ({
  runEnterpriseAgent: mocks.runEnterpriseAgent,
}));

import { enterpriseRuntimeHandlers } from "./enterprise-runtime.js";

let tempRoot: string;

async function writeRuntimeConfig(
  configPath: string,
  params?: { allowOverride?: boolean; maxRunSeconds?: number },
) {
  await fs.writeFile(
    configPath,
    JSON.stringify(
      {
        runtimeConfigs: [
          {
            id: "coding-default",
            version: "v1",
            stateDir: path.join(tempRoot, "state"),
            logsDir: path.join(tempRoot, "logs"),
            tmpRoot: path.join(tempRoot, "tmp"),
            model: {
              modelProfileId: "openai-gpt5",
              thinking: "medium",
            },
            tools: {
              allow: ["read", "write"],
            },
            limits: {
              maxRunSeconds: params?.maxRunSeconds ?? 1,
            },
            overridePolicy: params?.allowOverride
              ? {
                  model: {
                    allowedFields: ["thinking"],
                    allowedThinking: ["high"],
                  },
                }
              : undefined,
          },
        ],
        modelProfiles: [
          {
            id: "openai-gpt5",
            provider: "openai",
            model: "gpt-5",
            api: "openai",
            authPoolId: "openai-prod",
          },
        ],
        credentialPools: [
          {
            id: "openai-prod",
            provider: "openai",
            acquireTimeoutMs: 20,
            keys: [
              {
                keyId: "openai-prod-001",
                secretRef: "env:OPENCLAW_TEST_ENTERPRISE_KEY",
                models: ["gpt-5"],
                maxConcurrent: 1,
              },
            ],
          },
        ],
      },
      null,
      2,
    ),
    "utf8",
  );
}

function runtimeSpec(workspaceDir: string, configPath: string): RuntimeRunSpec {
  return {
    runId: "run-1",
    tenantId: "tenant-1",
    userId: "user-1",
    workspaceId: "workspace-1",
    threadId: "thread-1",
    runtimeConfigId: "coding-default",
    runtimeConfigVersion: "v1",
    workspace: {
      realPath: workspaceDir,
      accessMode: "write",
    },
    productSession: {
      threadId: "thread-1",
      openclawSessionKey:
        "runtime:tenant:tenant-1:user:user-1:workspace:workspace-1:thread:thread-1",
    },
    runtime: {
      configPath,
    },
    input: {
      message: "Update this workspace.",
    },
  };
}

async function invokeEnterpriseRuntime(params: unknown) {
  const respond = vi.fn();
  await enterpriseRuntimeHandlers[ENTERPRISE_RUNTIME_METHOD]!({
    req: { type: "req", id: "req-1", method: ENTERPRISE_RUNTIME_METHOD, params },
    params: params as Record<string, unknown>,
    client: null,
    isWebchatConnect: () => false,
    respond,
    context: {} as never,
  });
  return respond;
}

describe("enterprise.runtime.run handler", () => {
  beforeEach(async () => {
    tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-enterprise-runtime-handler-"));
    process.env.OPENCLAW_TEST_ENTERPRISE_KEY = "sk-enterprise-test";
    mocks.getRuntimeConfig.mockReturnValue({
      agents: {
        defaults: {
          workspace: "/must/not/use",
        },
      },
      models: {
        providers: {
          openai: {
            apiKey: "global-key-must-not-leak",
            auth: "api-key",
            models: [],
          },
        },
      },
    });
    mocks.runEnterpriseAgent.mockImplementation(async (ctx) => ({
      result: {
        finalAnswer: `Done with ${ctx.modelKeyLease?.keyId ?? "no-key"}.`,
      },
      rawAgentResult: {
        payloads: [{ text: "Done." }],
      },
    }));
  });

  afterEach(async () => {
    delete process.env.OPENCLAW_TEST_ENTERPRISE_KEY;
    mocks.getRuntimeConfig.mockReset();
    mocks.runEnterpriseAgent.mockReset();
    brokerTesting.states.clear();
    brokerTesting.roundRobin.clear();
    await fs.rm(tempRoot, { recursive: true, force: true });
  });

  it("builds a run context, leases a key, writes runtime artifacts, and returns a result", async () => {
    const workspaceDir = path.join(tempRoot, "workspace");
    const configPath = path.join(tempRoot, "runtime.json");
    await fs.mkdir(workspaceDir, { recursive: true });
    await writeRuntimeConfig(configPath);

    const respond = await invokeEnterpriseRuntime(runtimeSpec(workspaceDir, configPath));

    expect(respond).toHaveBeenCalledWith(
      true,
      expect.objectContaining({
        runId: "run-1",
        status: "succeeded",
        finalAnswer: "Done with openai-prod-001.",
        openclawSessionKey:
          "runtime:tenant:tenant-1:user:user-1:workspace:workspace-1:thread:thread-1",
        workspaceDir: await fs.realpath(workspaceDir),
        usage: expect.objectContaining({
          provider: "openai",
          model: "gpt-5",
          authPoolId: "openai-prod",
          keyId: "openai-prod-001",
        }),
      }),
      undefined,
    );

    const [[ctx, baseConfig]] = mocks.runEnterpriseAgent.mock.calls;
    expect(ctx.workspace.root).toBe(await fs.realpath(workspaceDir));
    expect(ctx.session.namespace).toBe("enterprise-runtime");
    expect(ctx.session.sessionKey).toBe(
      "runtime:tenant:tenant-1:user:user-1:workspace:workspace-1:thread:thread-1",
    );
    expect(baseConfig.agents.defaults.workspace).toBe("/must/not/use");

    const result = respond.mock.calls[0]?.[1] as { logs: { eventsPath: string } };
    const events = await fs.readFile(result.logs.eventsPath, "utf8");
    expect(events).toContain("run.accepted");
    expect(events).toContain("model.lease.acquired");
    await expect(
      fs.access(
        path.join(tempRoot, "state", "enterprise-runtime", "config-snapshots", "run-1.json"),
      ),
    ).resolves.toBeUndefined();
    await expect(
      fs.access(path.join(tempRoot, "logs", "runs", "run-1", "result.json")),
    ).resolves.toBeUndefined();
  });

  it("rejects forbidden model overrides before running the agent", async () => {
    const workspaceDir = path.join(tempRoot, "workspace");
    const configPath = path.join(tempRoot, "runtime.json");
    await fs.mkdir(workspaceDir, { recursive: true });
    await writeRuntimeConfig(configPath);

    const respond = await invokeEnterpriseRuntime({
      ...runtimeSpec(workspaceDir, configPath),
      modelOverride: { model: "gpt-5-mini" },
    });

    expect(mocks.runEnterpriseAgent).not.toHaveBeenCalled();
    expect(respond).toHaveBeenCalledWith(
      false,
      undefined,
      expect.objectContaining({
        message: expect.stringContaining("model override 'model' is not allowed"),
      }),
    );
  });

  it("starts maxRunSeconds timeout only after the run becomes active", async () => {
    const workspaceDir = path.join(tempRoot, "workspace");
    const configPath = path.join(tempRoot, "runtime.json");
    await fs.mkdir(workspaceDir, { recursive: true });
    await writeRuntimeConfig(configPath, { maxRunSeconds: 0.02 });
    mocks.runEnterpriseAgent.mockImplementation(
      async (ctx) =>
        await new Promise((_, reject) => {
          ctx.abortSignal?.addEventListener("abort", () => reject(ctx.abortSignal?.reason), {
            once: true,
          });
        }),
    );

    const respond = await invokeEnterpriseRuntime(runtimeSpec(workspaceDir, configPath));
    expect(mocks.runEnterpriseAgent).toHaveBeenCalledTimes(1);
    expect(respond).toHaveBeenCalledWith(
      true,
      expect.objectContaining({
        status: "timeout",
        error: expect.objectContaining({ code: "RUNTIME_TIMEOUT" }),
      }),
      undefined,
    );
  });

  it("does not spend maxRunSeconds while a run is waiting in the workspace queue", async () => {
    const workspaceDir = path.join(tempRoot, "workspace");
    const firstConfigPath = path.join(tempRoot, "runtime-first.json");
    const secondConfigPath = path.join(tempRoot, "runtime-second.json");
    await fs.mkdir(workspaceDir, { recursive: true });
    await writeRuntimeConfig(firstConfigPath, { maxRunSeconds: 5 });
    await writeRuntimeConfig(secondConfigPath, { maxRunSeconds: 0.1 });
    let firstStarted!: () => void;
    let releaseFirst!: () => void;
    const firstStartedPromise = new Promise<void>((resolve) => {
      firstStarted = resolve;
    });
    const releaseFirstPromise = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    let secondActiveAt = 0;
    mocks.runEnterpriseAgent.mockImplementation(async (ctx) => {
      if (ctx.runId === "run-1") {
        firstStarted();
        await releaseFirstPromise;
        return {
          result: { finalAnswer: "first" },
          rawAgentResult: { payloads: [] },
        };
      }
      secondActiveAt = Date.now();
      return await new Promise((_, reject) => {
        ctx.abortSignal?.addEventListener("abort", () => reject(ctx.abortSignal?.reason), {
          once: true,
        });
      });
    });

    const first = invokeEnterpriseRuntime(runtimeSpec(workspaceDir, firstConfigPath));
    await firstStartedPromise;
    const second = invokeEnterpriseRuntime({
      ...runtimeSpec(workspaceDir, secondConfigPath),
      runId: "run-2",
    });
    let secondSettled = false;
    void second.then(() => {
      secondSettled = true;
    });

    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(secondSettled).toBe(false);
    releaseFirst();

    const firstRespond = await first;
    expect(firstRespond).toHaveBeenCalledWith(
      true,
      expect.objectContaining({ runId: "run-1", status: "succeeded" }),
      undefined,
    );
    await vi.waitFor(() => expect(mocks.runEnterpriseAgent).toHaveBeenCalledTimes(2));

    const secondRespond = await second;
    const activeElapsedMs = Date.now() - secondActiveAt;

    expect(activeElapsedMs).toBeGreaterThanOrEqual(80);
    expect(secondRespond).toHaveBeenCalledWith(
      true,
      expect.objectContaining({ runId: "run-2", status: "timeout" }),
      undefined,
    );
  });
});
