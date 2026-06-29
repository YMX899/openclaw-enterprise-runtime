import { describe, expect, it } from "vitest";
import type { RuntimeRunSpec } from "../../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { resolveRuntimeConfigSnapshot } from "./resolve-snapshot.js";
import type { EnterpriseRuntimeConfigFile } from "./types.js";

function spec(): RuntimeRunSpec {
  return {
    runId: "run-1",
    tenantId: "tenant-1",
    userId: "user-1",
    workspaceId: "workspace-1",
    threadId: "thread-1",
    runtimeConfigId: "coding-default",
    workspace: { realPath: "/workspace", accessMode: "write" },
    productSession: {
      threadId: "thread-1",
      openclawSessionKey:
        "runtime:tenant:tenant-1:user:user-1:workspace:workspace-1:thread:thread-1",
    },
    input: { message: "hello" },
  };
}

describe("resolveRuntimeConfigSnapshot", () => {
  it("freezes model profile, runtime config, and allowed run override fields", () => {
    const configFile: EnterpriseRuntimeConfigFile = {
      runtimeConfigs: [
        {
          id: "coding-default",
          version: "v1",
          model: {
            modelProfileId: "profile-1",
            thinking: "medium",
            params: { temperature: 0.1 },
          },
          overridePolicy: {
            model: {
              allowedFields: ["thinking", "params"],
              allowedThinking: ["high"],
              allowParams: ["top_p"],
            },
          },
        },
      ],
      modelProfiles: [
        {
          id: "profile-1",
          provider: "openai",
          model: "gpt-5",
          api: "openai-responses",
          baseUrl: "https://api.example.test/v1",
          authPoolId: "pool-1",
          contextWindow: 256_000,
          contextTokens: 180_000,
          maxTokens: 8192,
          reasoning: "stream",
          reasoningEnabled: true,
          params: { store: false },
          cost: { input: 1, output: 2 },
          authHeader: true,
        },
      ],
      credentialPools: [
        {
          id: "pool-1",
          provider: "openai",
          keys: [{ keyId: "key-1", secretRef: "env:OPENAI_API_KEY" }],
        },
      ],
    };

    const { runtimeConfig, snapshot } = resolveRuntimeConfigSnapshot({
      configFile,
      spec: {
        ...spec(),
        runtimeConfigVersion: "v1",
        modelOverride: {
          thinking: "high",
          params: { top_p: 0.9 },
        },
      },
    });

    expect(runtimeConfig.id).toBe("coding-default");
    expect(snapshot.model).toMatchObject({
      modelProfileId: "profile-1",
      provider: "openai",
      model: "gpt-5",
      api: "openai-responses",
      baseUrl: "https://api.example.test/v1",
      authPoolId: "pool-1",
      thinking: "high",
      reasoning: "stream",
      reasoningEnabled: true,
      contextWindow: 256_000,
      contextTokens: 180_000,
      maxTokens: 8192,
      params: { store: false, temperature: 0.1, top_p: 0.9 },
      cost: { input: 1, output: 2 },
      authHeader: true,
    });
    expect(snapshot.sourceRefs.credentialPoolHash).toBeTruthy();
  });

  it("rejects unallowed model override fields before queueing", () => {
    const configFile: EnterpriseRuntimeConfigFile = {
      runtimeConfigs: [
        {
          id: "coding-default",
          model: { modelProfileId: "profile-1" },
        },
      ],
      modelProfiles: [{ id: "profile-1", provider: "openai", model: "gpt-5" }],
    };

    expect(() =>
      resolveRuntimeConfigSnapshot({
        configFile,
        spec: { ...spec(), modelOverride: { model: "gpt-5-mini" } },
      }),
    ).toThrow(/model override 'model' is not allowed/);
  });

  it("requires an auth pool for enterprise model requests", () => {
    const configFile: EnterpriseRuntimeConfigFile = {
      runtimeConfigs: [
        {
          id: "coding-default",
          model: { modelProfileId: "profile-1" },
        },
      ],
      modelProfiles: [{ id: "profile-1", provider: "openai", model: "gpt-5" }],
    };

    expect(() => resolveRuntimeConfigSnapshot({ configFile, spec: spec() })).toThrow(
      /model authPoolId is required/,
    );
  });

  it("requires the configured auth pool to exist", () => {
    const configFile: EnterpriseRuntimeConfigFile = {
      runtimeConfigs: [
        {
          id: "coding-default",
          model: { modelProfileId: "profile-1", authPoolId: "missing-pool" },
        },
      ],
      modelProfiles: [{ id: "profile-1", provider: "openai", model: "gpt-5" }],
      credentialPools: [],
    };

    expect(() => resolveRuntimeConfigSnapshot({ configFile, spec: spec() })).toThrow(
      /credential pool not found: missing-pool/,
    );
  });

  it("hard-disables subagent orchestration tools in enterprise runtime snapshots", () => {
    const configFile: EnterpriseRuntimeConfigFile = {
      runtimeConfigs: [
        {
          id: "coding-default",
          model: { modelProfileId: "profile-1" },
          tools: {
            allow: [
              "read",
              "sessions_spawn",
              "sessions_list",
              "sessions_history",
              "sessions_send",
              "subagents",
              "agents_list",
              "sessions_yield",
            ],
            deny: ["write"],
          },
        },
      ],
      modelProfiles: [
        {
          id: "profile-1",
          provider: "openai",
          model: "gpt-5",
          authPoolId: "pool-1",
        },
      ],
      credentialPools: [
        {
          id: "pool-1",
          provider: "openai",
          keys: [{ keyId: "key-1", secretRef: "env:OPENAI_API_KEY" }],
        },
      ],
    };

    const { snapshot } = resolveRuntimeConfigSnapshot({
      configFile,
      spec: {
        ...spec(),
        tools: {
          allow: ["sessions_spawn", "sessions_list", "read"],
          deny: ["subagents"],
        },
      },
    });

    expect(snapshot.tools.allow).toEqual(["read"]);
    expect(snapshot.tools.deny).toEqual([
      "write",
      "subagents",
      "sessions_spawn",
      "sessions_yield",
      "sessions_list",
      "sessions_history",
      "sessions_send",
      "agents_list",
    ]);
  });
});
