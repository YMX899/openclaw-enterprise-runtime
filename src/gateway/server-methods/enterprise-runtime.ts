import {
  ErrorCodes,
  errorShape,
  formatValidationErrors,
  validateRuntimeRunSpec,
} from "../../../packages/gateway-protocol/src/index.js";
import type { RuntimeRunSpec } from "../../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { getRuntimeConfig } from "../../config/io.js";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { runEnterpriseAgent } from "../../enterprise-runtime/agent-runner.js";
import { resolveRuntimeAttachments } from "../../enterprise-runtime/attachments.js";
import { loadEnterpriseRuntimeConfigFile } from "../../enterprise-runtime/config/load-runtime-config.js";
import {
  assertEnterpriseShellPolicy,
  assertReadModeTools,
} from "../../enterprise-runtime/config/override-policy.js";
import { resolveRuntimeConfigSnapshot } from "../../enterprise-runtime/config/resolve-snapshot.js";
import { saveResolvedRuntimeConfigSnapshot } from "../../enterprise-runtime/config/snapshot-store.js";
import {
  ENTERPRISE_RUNTIME_METHOD,
  ENTERPRISE_RUNTIME_SESSION_NAMESPACE,
} from "../../enterprise-runtime/constants.js";
import { EnterpriseRuntimeError } from "../../enterprise-runtime/errors.js";
import { RuntimeEventLogger } from "../../enterprise-runtime/event-logger.js";
import { acquireModelKeyLease } from "../../enterprise-runtime/model-broker/broker.js";
import { classifyModelKeyLeaseError } from "../../enterprise-runtime/model-broker/error-classification.js";
import {
  resolveEnterpriseRuntimeConfigPath,
  resolveRuntimeDirs,
  resolveRuntimeStoreDirs,
  resolveRuntimeWorkspace,
} from "../../enterprise-runtime/paths.js";
import { buildRuntimeRunResult, statusForError } from "../../enterprise-runtime/result.js";
import {
  buildEnterpriseSessionLockKey,
  runWithSessionLock,
} from "../../enterprise-runtime/session-lock.js";
import {
  assertNoStalledRuntimeRun,
  clearRuntimeRunStalled,
  markRuntimeRunStalled,
} from "../../enterprise-runtime/stalled-run-guard.js";
import type { RuntimeRunContext } from "../../enterprise-runtime/types.js";
import { runWithWorkspaceQueue } from "../../enterprise-runtime/workspace-queue.js";
import type { GatewayRequestHandlers } from "./types.js";

function assertRuntimeModelSupportsAttachments(ctx: RuntimeRunContext): void {
  const hasImageAttachment = ctx.attachments.some((attachment) => attachment.image);
  if (!hasImageAttachment) {
    return;
  }
  if (ctx.configSnapshot.model.input?.includes("image")) {
    return;
  }
  throw new EnterpriseRuntimeError(
    "RUNTIME_MODEL_INPUT_UNSUPPORTED",
    "current model profile does not support image input",
    {
      provider: ctx.configSnapshot.model.provider,
      model: ctx.configSnapshot.model.model,
      input: ctx.configSnapshot.model.input ?? ["text"],
      attachmentCount: ctx.attachments.length,
    },
  );
}

function resolveMaxRunMs(fallbackSeconds?: number): number | undefined {
  const seconds = fallbackSeconds;
  if (seconds === undefined || seconds <= 0) {
    return undefined;
  }
  return Math.ceil(seconds * 1000);
}

function createAbortSignal(maxRunMs: number | undefined): {
  signal: AbortSignal;
  dispose: () => void;
} {
  const controller = new AbortController();
  if (!maxRunMs) {
    return { signal: controller.signal, dispose: () => undefined };
  }
  const timer = setTimeout(() => {
    controller.abort(
      new EnterpriseRuntimeError("RUNTIME_TIMEOUT", "enterprise runtime run timed out"),
    );
  }, maxRunMs);
  return {
    signal: controller.signal,
    dispose: () => clearTimeout(timer),
  };
}

function timeoutError(): EnterpriseRuntimeError {
  return new EnterpriseRuntimeError("RUNTIME_TIMEOUT", "enterprise runtime run timed out");
}

async function runWithHardTimeout<T>(params: {
  signal?: AbortSignal;
  task: () => Promise<T>;
  onDetachedTimeout?: () => void;
  onDetachedTaskSettled?: () => void;
}): Promise<T> {
  const signal = params.signal;
  if (!signal) {
    return await params.task();
  }
  if (signal.aborted) {
    throw signal.reason instanceof Error ? signal.reason : timeoutError();
  }
  return await new Promise<T>((resolve, reject) => {
    let settled = false;
    let detached = false;
    const finish = (fn: typeof resolve | typeof reject, value: T | unknown) => {
      if (settled) {
        return;
      }
      settled = true;
      signal.removeEventListener("abort", onAbort);
      fn(value as T);
    };
    const onAbort = () => {
      detached = true;
      params.onDetachedTimeout?.();
      finish(reject, signal.reason instanceof Error ? signal.reason : timeoutError());
    };
    const finishTask = (fn: typeof resolve | typeof reject, value: T | unknown) => {
      if (detached) {
        params.onDetachedTaskSettled?.();
      }
      finish(fn, value);
    };
    signal.addEventListener("abort", onAbort, { once: true });
    void params.task().then(
      (value) => finishTask(resolve, value),
      (error) => finishTask(reject, error),
    );
  });
}

async function buildRunContext(spec: RuntimeRunSpec): Promise<{
  ctx: RuntimeRunContext;
  baseConfig: OpenClawConfig;
}> {
  const workspace = await resolveRuntimeWorkspace(spec);
  const configPath = resolveEnterpriseRuntimeConfigPath(spec);
  const configFile = await loadEnterpriseRuntimeConfigFile(configPath);
  const { runtimeConfig, snapshot } = resolveRuntimeConfigSnapshot({ configFile, spec });
  const baseConfig = getRuntimeConfig({ pin: false });
  const storeDirs = resolveRuntimeStoreDirs({ configFile, runtimeConfig });
  const dirs = await resolveRuntimeDirs({
    spec,
    workspaceRoot: workspace.root,
    configStateDir: storeDirs.stateDir,
    configLogsDir: storeDirs.logsDir,
    configTmpRoot: storeDirs.tmpRoot,
  });
  await saveResolvedRuntimeConfigSnapshot({ stateDir: dirs.stateDir, snapshot });

  return {
    ctx: {
      runId: spec.runId,
      tenantId: spec.tenantId,
      userId: spec.userId,
      workspaceId: spec.workspaceId,
      threadId: spec.threadId,
      spec,
      workspace: {
        root: workspace.root,
        queueKey: workspace.queueKey,
        accessMode: spec.workspace.accessMode,
      },
      session: {
        namespace: ENTERPRISE_RUNTIME_SESSION_NAMESPACE,
        sessionKey: spec.productSession.openclawSessionKey,
      },
      input: spec.input,
      attachments: [],
      configSnapshot: snapshot,
      credentialPools: configFile.credentialPools,
      dirs,
      boundary: {
        root: workspace.root,
        accessMode: spec.workspace.accessMode,
        ...(snapshot.tools.allow ? { toolsAllow: snapshot.tools.allow } : {}),
        ...(snapshot.tools.deny ? { toolsDeny: snapshot.tools.deny } : {}),
      },
    },
    baseConfig,
  };
}

export const enterpriseRuntimeHandlers: GatewayRequestHandlers = {
  [ENTERPRISE_RUNTIME_METHOD]: async ({ params, respond }) => {
    if (!validateRuntimeRunSpec(params)) {
      respond(
        false,
        undefined,
        errorShape(
          ErrorCodes.INVALID_REQUEST,
          `invalid ${ENTERPRISE_RUNTIME_METHOD} params: ${formatValidationErrors(
            validateRuntimeRunSpec.errors,
          )}`,
        ),
      );
      return;
    }

    let ctx: RuntimeRunContext | undefined;
    let baseConfig: OpenClawConfig | undefined;
    let logger: RuntimeEventLogger | undefined;
    let activeKeyId: string | undefined;
    let activeRunAborted = false;
    try {
      const built = await buildRunContext(params);
      ctx = built.ctx;
      baseConfig = built.baseConfig;
      const lockKey = buildEnterpriseSessionLockKey(ctx.session.namespace, ctx.session.sessionKey);
      const stalledEntries = [
        { scope: "workspace" as const, key: ctx.workspace.queueKey },
        { scope: "session" as const, key: lockKey },
      ];
      assertNoStalledRuntimeRun(stalledEntries);
      logger = new RuntimeEventLogger(ctx);
      await logger.event({ eventType: "run.accepted" });
      await logger.event({ eventType: "config.snapshot.created" });
      await logger.event({ eventType: "workspace.boundary.created" });
      ctx.attachments = await resolveRuntimeAttachments({
        spec: params,
        workspaceRoot: ctx.workspace.root,
      });
      await logger.event({
        eventType: "attachments.resolved",
        attachmentCount: ctx.attachments.length,
      });
      assertRuntimeModelSupportsAttachments(ctx);
      const sandboxed = false;
      assertEnterpriseShellPolicy({ toolsAllow: ctx.configSnapshot.tools.allow, sandboxed });
      if (ctx.workspace.accessMode === "read") {
        assertReadModeTools(ctx.configSnapshot.tools.allow);
      }

      const completed = await runWithWorkspaceQueue(ctx.workspace.queueKey, async (queue) => {
        await logger?.event({ eventType: "run.queued", queue });
        return await runWithSessionLock(lockKey, async () => {
          await logger?.event({ eventType: "session.lock.acquired" });
          const abort = createAbortSignal(
            resolveMaxRunMs(ctx!.configSnapshot.limits?.maxRunSeconds),
          );
          ctx!.abortSignal = abort.signal;
          await logger?.event({ eventType: "run.started" });
          try {
            const lease = await acquireModelKeyLease({
              pools: ctx!.credentialPools,
              authPoolId: ctx!.configSnapshot.model.authPoolId ?? "",
              provider: ctx!.configSnapshot.model.provider,
              model: ctx!.configSnapshot.model.model,
              signal: ctx!.abortSignal,
            });
            ctx!.modelKeyLease = lease;
            activeKeyId = lease?.keyId;
            if (lease) {
              await logger?.event({
                eventType: "model.lease.acquired",
                authPoolId: lease.authPoolId,
                keyId: lease.keyId,
              });
            }
            let leaseReleaseDeferredToDetachedTask = false;
            try {
              const agent = await runWithHardTimeout({
                signal: ctx!.abortSignal,
                task: () => runEnterpriseAgent(ctx!, baseConfig!),
                onDetachedTimeout: () => {
                  leaseReleaseDeferredToDetachedTask = true;
                  markRuntimeRunStalled({ entries: stalledEntries, runId: ctx!.runId });
                },
                onDetachedTaskSettled: () => {
                  clearRuntimeRunStalled({ entries: stalledEntries, runId: ctx!.runId });
                  lease?.release("overloaded");
                  ctx!.modelKeyLease = undefined;
                },
              });
              const fallbackResult = buildRuntimeRunResult({
                ctx: ctx!,
                status: "succeeded",
                finalAnswer: agent.result.finalAnswer,
                queue,
                keyId: lease?.keyId,
              });
              return {
                ...fallbackResult,
                ...agent.result,
                queue,
                session: {
                  ...fallbackResult.session,
                  ...agent.result.session,
                },
                logs: {
                  ...fallbackResult.logs,
                  ...agent.result.logs,
                },
                usage: {
                  ...fallbackResult.usage,
                  ...agent.result.usage,
                  ...(lease?.keyId && !agent.result.usage?.keyId ? { keyId: lease.keyId } : {}),
                },
              };
            } catch (error) {
              if (!leaseReleaseDeferredToDetachedTask) {
                lease?.release(
                  ctx!.abortSignal?.aborted ? "overloaded" : classifyModelKeyLeaseError(error),
                );
              }
              throw error;
            } finally {
              if (!leaseReleaseDeferredToDetachedTask) {
                lease?.release();
                ctx!.modelKeyLease = undefined;
              }
            }
          } finally {
            activeRunAborted = ctx!.abortSignal?.aborted === true;
            ctx!.abortSignal = undefined;
            abort.dispose();
          }
        });
      });

      await logger.event({
        eventType: "run.finished",
        status: completed.result.status,
      });
      await logger.result(completed.result);
      respond(true, completed.result, undefined);
    } catch (error) {
      if (logger) {
        await logger.error(error);
      }
      if (!ctx) {
        respond(
          false,
          undefined,
          errorShape(
            ErrorCodes.INVALID_REQUEST,
            error instanceof Error ? error.message : String(error),
          ),
        );
        return;
      }
      const result = buildRuntimeRunResult({
        ctx,
        status: statusForError(error, { aborted: activeRunAborted || ctx.abortSignal?.aborted }),
        error,
        keyId: activeKeyId,
      });
      await logger?.event({
        eventType: result.status === "timeout" ? "run.timeout" : "run.failed",
      });
      await logger?.result(result);
      respond(true, result, undefined);
    }
  },
};
