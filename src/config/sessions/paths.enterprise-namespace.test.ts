import path from "node:path";
import { describe, expect, it } from "vitest";
import { resolveStorePath } from "./paths.js";

describe("enterprise session store namespace paths", () => {
  it("uses sessionStoreNamespace ahead of agentId for default store paths", () => {
    const env = {
      OPENCLAW_STATE_DIR: "/var/lib/openclaw",
    } as NodeJS.ProcessEnv;

    expect(
      resolveStorePath(undefined, {
        agentId: "main",
        sessionStoreNamespace: "enterprise-runtime",
        env,
      }),
    ).toBe(path.resolve("/var/lib/openclaw/agents/enterprise-runtime/sessions/sessions.json"));
  });

  it("expands both namespace and legacy agent templates with the enterprise namespace", () => {
    const env = {} as NodeJS.ProcessEnv;

    expect(
      resolveStorePath("/state/agents/{sessionStoreNamespace}/sessions/sessions.json", {
        agentId: "main",
        sessionStoreNamespace: "enterprise-runtime",
        env,
      }),
    ).toBe(path.resolve("/state/agents/enterprise-runtime/sessions/sessions.json"));
    expect(
      resolveStorePath("/state/agents/{agentId}/sessions/sessions.json", {
        agentId: "main",
        sessionStoreNamespace: "enterprise-runtime",
        env,
      }),
    ).toBe(path.resolve("/state/agents/enterprise-runtime/sessions/sessions.json"));
  });
});
