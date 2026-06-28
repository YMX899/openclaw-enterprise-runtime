import fs from "node:fs/promises";
import path from "node:path";
import type { RuntimeRunResult } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { redactSecrets } from "../logging/redact.js";
import type { RuntimeRunContext } from "./types.js";

type RuntimeEvent = {
  eventType: string;
  timestamp?: string;
  [key: string]: unknown;
};

export class RuntimeEventLogger {
  readonly eventsPath: string;
  readonly accessDenyPath: string;
  readonly errorPath: string;
  readonly resultPath: string;

  constructor(private readonly ctx: RuntimeRunContext) {
    this.eventsPath = path.join(ctx.dirs.runDir, "events.jsonl");
    this.accessDenyPath = path.join(ctx.dirs.runDir, "access-deny.jsonl");
    this.errorPath = path.join(ctx.dirs.runDir, "error.json");
    this.resultPath = path.join(ctx.dirs.runDir, "result.json");
  }

  private base() {
    return {
      runId: this.ctx.runId,
      tenantId: this.ctx.tenantId,
      userId: this.ctx.userId,
      workspaceId: this.ctx.workspaceId,
      threadId: this.ctx.threadId,
      openclawSessionKey: this.ctx.session.sessionKey,
      workspaceDir: this.ctx.workspace.root,
      resolvedConfigSnapshotId: this.ctx.configSnapshot.snapshotId,
    };
  }

  async event(event: RuntimeEvent): Promise<void> {
    await fs.mkdir(this.ctx.dirs.runDir, { recursive: true });
    await fs.appendFile(
      this.eventsPath,
      `${JSON.stringify({ timestamp: new Date().toISOString(), ...this.base(), ...event })}\n`,
      "utf8",
    );
  }

  async error(error: unknown): Promise<void> {
    const payload = {
      timestamp: new Date().toISOString(),
      ...this.base(),
      error: redactSecrets(
        error instanceof Error
          ? { name: error.name, message: error.message, stack: error.stack }
          : String(error),
      ),
    };
    await fs.writeFile(this.errorPath, JSON.stringify(payload, null, 2), "utf8");
  }

  async result(result: RuntimeRunResult): Promise<void> {
    await fs.writeFile(this.resultPath, JSON.stringify(result, null, 2), "utf8");
  }
}
