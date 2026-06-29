import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { ENTERPRISE_RUNTIME_SESSION_NAMESPACE } from "./constants.js";
import {
  buildEnterpriseRuntimeSessionResult,
  resolveEnterpriseRuntimeSessionStorePath,
} from "./session-store.js";
import type { RuntimeRunContext } from "./types.js";

describe("enterprise runtime session store result", () => {
  let tempRoot: string | undefined;

  afterEach(async () => {
    if (tempRoot) {
      await fs.rm(tempRoot, { recursive: true, force: true });
      tempRoot = undefined;
    }
  });

  async function makeContext(): Promise<RuntimeRunContext> {
    tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-enterprise-session-store-"));
    return {
      runId: "run-1",
      tenantId: "tenant-1",
      userId: "user-1",
      workspaceId: "workspace-1",
      threadId: "thread-1",
      spec: {} as never,
      workspace: {
        root: path.join(tempRoot, "workspace"),
        queueKey: "workspace-1",
        accessMode: "write",
      },
      session: {
        namespace: ENTERPRISE_RUNTIME_SESSION_NAMESPACE,
        sessionKey: "runtime:tenant:tenant-1:user:user-1:workspace:workspace-1:thread:thread-1",
      },
      input: {
        message: "hello",
      },
      attachments: [],
      configSnapshot: {
        snapshotId: "snapshot-1",
        runtimeConfigId: "coding-default",
        runtimeConfigVersion: "v1",
        createdAt: new Date().toISOString(),
        model: {
          provider: "openai",
          model: "gpt-5",
          input: ["text"],
        },
        tools: {
          allow: ["read", "write"],
        },
      },
      dirs: {
        stateDir: path.join(tempRoot, "state"),
        configPath: path.join(tempRoot, "runtime.json"),
        logsDir: path.join(tempRoot, "logs"),
        tmpDir: path.join(tempRoot, "tmp"),
        runDir: path.join(tempRoot, "logs", "runs", "run-1"),
      },
      boundary: {
        root: path.join(tempRoot, "workspace"),
        accessMode: "write",
      },
    } as RuntimeRunContext;
  }

  it("returns transcript paths only from the enterprise runtime stateDir session store", async () => {
    const ctx = await makeContext();
    const storePath = resolveEnterpriseRuntimeSessionStorePath(ctx.dirs.stateDir);
    const sessionsDir = path.dirname(storePath);
    await fs.mkdir(sessionsDir, { recursive: true });
    await fs.writeFile(
      storePath,
      JSON.stringify({
        [ctx.session.sessionKey]: {
          sessionId: "session-1",
          sessionFile: "session-1.jsonl",
        },
      }),
      "utf8",
    );

    const result = buildEnterpriseRuntimeSessionResult({
      ctx,
      sessionId: "session-1",
      sessionFile: path.join(tempRoot!, "global-openclaw-data", "session-1.jsonl"),
    });

    expect(result).toEqual({
      namespace: "enterprise-runtime",
      storePath,
      sessionId: "session-1",
      filePath: path.join(sessionsDir, "session-1.jsonl"),
    });
  });

  it("does not expose an agent-provided session file outside stateDir", async () => {
    const ctx = await makeContext();
    const storePath = resolveEnterpriseRuntimeSessionStorePath(ctx.dirs.stateDir);

    const result = buildEnterpriseRuntimeSessionResult({
      ctx,
      sessionId: "session-1",
      sessionFile: path.join(tempRoot!, "global-openclaw-data", "session-1.jsonl"),
    });

    expect(result).toEqual({
      namespace: "enterprise-runtime",
      storePath,
      sessionId: "session-1",
    });
  });
});
