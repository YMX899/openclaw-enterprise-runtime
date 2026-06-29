import type {
  RuntimeRunResult,
  RuntimeQueueState,
} from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { EnterpriseRuntimeError, toRuntimeError } from "./errors.js";
import { buildEnterpriseRuntimeSessionResult } from "./session-store.js";
import type { RuntimeRunContext } from "./types.js";

export function buildRuntimeRunResult(params: {
  ctx: RuntimeRunContext;
  status: RuntimeRunResult["status"];
  finalAnswer?: string;
  queue?: RuntimeQueueState;
  error?: unknown;
  keyId?: string;
}): RuntimeRunResult {
  const runtimeError = params.error ? toRuntimeError(params.error) : undefined;
  const result: RuntimeRunResult = {
    runId: params.ctx.runId,
    status: params.status,
    threadId: params.ctx.threadId,
    openclawSessionKey: params.ctx.session.sessionKey,
    workspaceDir: params.ctx.workspace.root,
    resolvedConfigSnapshotId: params.ctx.configSnapshot.snapshotId,
    session: buildEnterpriseRuntimeSessionResult({ ctx: params.ctx }),
    logs: {
      eventsPath: `${params.ctx.dirs.runDir}/events.jsonl`,
      accessDenyPath: `${params.ctx.dirs.runDir}/access-deny.jsonl`,
      ...(runtimeError ? { errorPath: `${params.ctx.dirs.runDir}/error.json` } : {}),
    },
    usage: {
      provider: params.ctx.configSnapshot.model.provider,
      model: params.ctx.configSnapshot.model.model,
      ...(params.ctx.configSnapshot.model.authPoolId
        ? { authPoolId: params.ctx.configSnapshot.model.authPoolId }
        : {}),
      ...(params.keyId ? { keyId: params.keyId } : {}),
      input: params.ctx.configSnapshot.model.input ?? ["text"],
      attachmentCount: params.ctx.attachments.length,
    },
    ...(params.finalAnswer !== undefined ? { finalAnswer: params.finalAnswer } : {}),
    ...(params.queue ? { queue: params.queue } : {}),
    ...(runtimeError ? { error: runtimeError } : {}),
  };
  return result;
}

export function statusForError(
  error: unknown,
  opts: { aborted?: boolean } = {},
): RuntimeRunResult["status"] {
  if (opts.aborted) {
    return "timeout";
  }
  if (error instanceof EnterpriseRuntimeError) {
    if (error.code === "RUNTIME_TIMEOUT") {
      return "timeout";
    }
    if (error.code === "RUNTIME_WORKSPACE_FORBIDDEN") {
      return "forbidden";
    }
  }
  return "failed";
}
