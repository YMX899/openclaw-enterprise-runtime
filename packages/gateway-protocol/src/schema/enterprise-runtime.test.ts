import { Value } from "typebox/value";
import { describe, expect, it } from "vitest";
import { ProtocolSchemas, validateRuntimeRunResult, validateRuntimeRunSpec } from "../index.js";
import { RuntimeRunResultSchema, RuntimeRunSpecSchema } from "./enterprise-runtime.js";

function validSpec() {
  return {
    runId: "run-1",
    tenantId: "tenant-1",
    userId: "user-1",
    workspaceId: "workspace-1",
    threadId: "thread-1",
    runtimeConfigId: "coding-default",
    workspace: {
      realPath: "/workspaces/user-1/project",
      accessMode: "write",
    },
    productSession: {
      threadId: "thread-1",
      openclawSessionKey:
        "runtime:tenant:tenant-1:user:user-1:workspace:workspace-1:thread:thread-1",
    },
    modelOverride: {
      thinking: "high",
      params: { temperature: 0.2 },
    },
    input: {
      message: "Update the workspace README.",
      attachments: [{ name: "brief", path: "/workspaces/user-1/project/brief.md" }],
    },
  };
}

function validResult() {
  return {
    runId: "run-1",
    status: "succeeded",
    threadId: "thread-1",
    openclawSessionKey: "runtime:tenant:tenant-1:user:user-1:workspace:workspace-1:thread:thread-1",
    workspaceDir: "/workspaces/user-1/project",
    resolvedConfigSnapshotId: "snapshot-1",
    finalAnswer: "Done.",
    session: {
      namespace: "enterprise-runtime",
      storePath: "/runtime/state/agents/enterprise-runtime/sessions/sessions.json",
      sessionId: "session-1",
      filePath: "/runtime/state/agents/enterprise-runtime/sessions/session-1.jsonl",
    },
    logs: {
      eventsPath: "/runtime/logs/runs/run-1/events.jsonl",
    },
    usage: {
      provider: "openai",
      model: "gpt-5",
      authPoolId: "openai-prod",
      keyId: "openai-prod-001",
      input: ["text", "image"],
      attachmentCount: 0,
    },
  };
}

describe("enterprise runtime protocol schema", () => {
  it("registers RuntimeRunSpec and RuntimeRunResult in ProtocolSchemas", () => {
    expect(ProtocolSchemas.RuntimeRunSpec).toBe(RuntimeRunSpecSchema);
    expect(ProtocolSchemas.RuntimeRunResult).toBe(RuntimeRunResultSchema);
  });

  it("validates a complete RuntimeRunSpec through schema and exported validator", () => {
    const spec = validSpec();
    expect(Value.Check(RuntimeRunSpecSchema, spec)).toBe(true);
    expect(validateRuntimeRunSpec(spec)).toBe(true);
  });

  it("rejects missing workspace, session key, message, and unknown model override fields", () => {
    expect(validateRuntimeRunSpec({ ...validSpec(), workspace: undefined })).toBe(false);
    expect(
      validateRuntimeRunSpec({
        ...validSpec(),
        productSession: { threadId: "thread-1" },
      }),
    ).toBe(false);
    expect(validateRuntimeRunSpec({ ...validSpec(), input: { message: "" } })).toBe(false);
    expect(
      validateRuntimeRunSpec({
        ...validSpec(),
        modelOverride: { thinking: "high", unsafe: true },
      }),
    ).toBe(false);
  });

  it("validates RuntimeRunResult and keeps result fields strict", () => {
    expect(validateRuntimeRunResult(validResult())).toBe(true);
    expect(validateRuntimeRunResult({ ...validResult(), status: "queued" })).toBe(false);
    expect(validateRuntimeRunResult({ ...validResult(), secret: "sk-test" })).toBe(false);
  });
});
