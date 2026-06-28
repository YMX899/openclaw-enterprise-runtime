import { describe, expect, it } from "vitest";
import { buildEnterpriseRunOpenClawConfig } from "./run-config.js";
import type { ResolvedRuntimeConfigSnapshot } from "./types.js";

function snapshot(): ResolvedRuntimeConfigSnapshot {
  return {
    snapshotId: "snap-1",
    runId: "run-1",
    createdAt: "2026-06-28T00:00:00.000Z",
    runtimeConfigId: "coding-default",
    model: {
      modelProfileId: "gpt-coding",
      provider: "openai",
      model: "gpt-5",
      api: "openai",
      baseUrl: "https://api.example.test/v1",
      authPoolId: "pool-1",
      fallbacks: ["openai/gpt-5-mini"],
      thinking: "high",
      reasoning: "stream",
      contextWindow: 256_000,
      contextTokens: 180_000,
      maxTokens: 8192,
      maxTokensField: "max_completion_tokens",
      timeoutSeconds: 600,
      params: { temperature: 0.2 },
      cost: { input: 1, output: 2 },
      authHeader: true,
    },
    tools: {},
    compaction: { enabled: true, reserveTokens: 4096 },
    limits: { maxRunSeconds: 900 },
    sourceRefs: { runtimeConfigHash: "runtime-hash" },
  };
}

describe("buildEnterpriseRunOpenClawConfig", () => {
  it("materializes snapshot model settings into an in-memory OpenClaw config", () => {
    const cfg = buildEnterpriseRunOpenClawConfig({
      baseConfig: {
        agents: {
          defaults: {
            workspace: "/must/not/use",
          },
        },
      },
      snapshot: snapshot(),
      lease: {
        authPoolId: "pool-1",
        keyId: "key-1",
        secret: "sk-test",
        release: () => undefined,
      },
    });

    expect(cfg.models?.providers?.openai).toMatchObject({
      baseUrl: "https://api.example.test/v1",
      api: "openai-responses",
      auth: "api-key",
      apiKey: "sk-test",
      timeoutSeconds: 600,
      authHeader: true,
      params: { temperature: 0.2 },
    });
    expect(cfg.models?.providers?.openai?.models[0]).toMatchObject({
      id: "gpt-5",
      api: "openai-responses",
      baseUrl: "https://api.example.test/v1",
      contextWindow: 256_000,
      contextTokens: 180_000,
      maxTokens: 8192,
      reasoning: true,
      input: ["text"],
      cost: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0 },
      params: { temperature: 0.2 },
    });
    expect(cfg.agents?.defaults?.model).toEqual({
      primary: "openai/gpt-5",
      fallbacks: ["openai/gpt-5-mini"],
    });
    expect(cfg.agents?.defaults?.workspace).toBe("/must/not/use");
    expect(cfg.agents?.defaults?.skipBootstrap).toBe(true);
    expect(cfg.agents?.defaults?.reasoningDefault).toBe("stream");
    expect(cfg.agents?.defaults?.compaction).toEqual({ enabled: true, reserveTokens: 4096 });
  });

  it("does not inject a key when no lease is present", () => {
    const cfg = buildEnterpriseRunOpenClawConfig({
      baseConfig: {
        models: {
          providers: {
            openai: {
              baseUrl: "https://global.example.test/v1",
              apiKey: "global-key-must-not-leak",
              auth: "api-key",
              headers: { Authorization: "Bearer global-key-must-not-leak" },
              models: [],
            },
          },
        },
      },
      snapshot: snapshot(),
    });

    expect(cfg.models?.providers?.openai?.apiKey).toBeUndefined();
    expect(cfg.models?.providers?.openai?.auth).toBeUndefined();
    expect(cfg.models?.providers?.openai?.headers).toBeUndefined();
  });
});
