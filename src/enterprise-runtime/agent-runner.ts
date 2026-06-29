import type { RuntimeRunResult } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { agentCommandFromIngress } from "../agents/agent-command.js";
import type { AgentCommandIngressOpts } from "../agents/command/types.js";
import type { OpenClawConfig } from "../config/types.openclaw.js";
import { defaultRuntime } from "../runtime.js";
import { buildEnterpriseRunOpenClawConfig } from "./config/run-config.js";
import { ENTERPRISE_RUNTIME_SESSION_NAMESPACE } from "./constants.js";
import { buildEnterpriseRuntimeSessionResult } from "./session-store.js";
import { applyEnterpriseRuntimeSubagentToolPolicy } from "./subagent-policy.js";
import type { RuntimeRunContext } from "./types.js";

function imageInputsFromContext(
  ctx: RuntimeRunContext,
): Pick<AgentCommandIngressOpts, "images" | "imageOrder"> {
  const images = ctx.attachments.flatMap((attachment) =>
    attachment.image ? [attachment.image] : [],
  );
  if (!images.length) {
    return {};
  }
  const imageOrder = (ctx.input.attachments ?? []).flatMap((inputAttachment) => {
    const resolved = ctx.attachments.find(
      (attachment) =>
        attachment.path === inputAttachment.path || attachment.name === inputAttachment.name,
    );
    return resolved?.image ? ["inline" as const] : [];
  });
  return {
    images,
    imageOrder: imageOrder.length ? imageOrder : images.map(() => "inline" as const),
  };
}

function finalAnswerFromAgentResult(
  result: Awaited<ReturnType<typeof agentCommandFromIngress>>,
): string | undefined {
  const payloads = Array.isArray(result?.payloads) ? result.payloads : [];
  const text = payloads
    .map((payload) => (typeof payload?.text === "string" ? payload.text : ""))
    .filter(Boolean)
    .join("\n\n")
    .trim();
  return text || undefined;
}

function rawAgentSessionMeta(result: Awaited<ReturnType<typeof agentCommandFromIngress>>): {
  sessionId?: unknown;
  sessionFile?: unknown;
} {
  return {
    sessionId: result?.meta?.agentMeta?.sessionId,
    sessionFile: result?.meta?.agentMeta?.sessionFile,
  };
}

export async function runEnterpriseAgent(
  ctx: RuntimeRunContext,
  baseConfig: OpenClawConfig,
): Promise<{
  result: RuntimeRunResult;
  rawAgentResult: Awaited<ReturnType<typeof agentCommandFromIngress>>;
}> {
  const runConfig = buildEnterpriseRunOpenClawConfig({
    baseConfig,
    snapshot: ctx.configSnapshot,
    stateDir: ctx.dirs.stateDir,
    lease: ctx.modelKeyLease,
  });
  const imageInput = imageInputsFromContext(ctx);
  const tools = applyEnterpriseRuntimeSubagentToolPolicy(ctx.configSnapshot.tools);
  const agentOpts: AgentCommandIngressOpts = {
    message: ctx.input.message,
    transcriptMessage: ctx.input.message,
    ...imageInput,
    sessionKey: ctx.session.sessionKey,
    sessionStoreNamespace: ENTERPRISE_RUNTIME_SESSION_NAMESPACE,
    workspaceDir: ctx.workspace.root,
    cwd: ctx.workspace.root,
    runId: ctx.runId,
    provider: ctx.configSnapshot.model.provider,
    model: ctx.configSnapshot.model.model,
    thinking: ctx.configSnapshot.model.thinking,
    timeout:
      ctx.configSnapshot.model.timeoutSeconds !== undefined
        ? String(ctx.configSnapshot.model.timeoutSeconds)
        : undefined,
    promptMode: ctx.configSnapshot.prompt?.mode,
    extraSystemPrompt: ctx.configSnapshot.prompt?.extraSystemPrompt,
    toolsAllow: tools.allow,
    toolsDeny: tools.deny,
    senderIsOwner: true,
    allowModelOverride: true,
    deliver: false,
    sessionEffects: "visible",
    suppressPromptPersistence: false,
    abortSignal: ctx.abortSignal,
    enterpriseRuntime: {
      runContext: ctx,
      sessionStoreNamespace: ENTERPRISE_RUNTIME_SESSION_NAMESPACE,
      resolvedConfigSnapshotId: ctx.configSnapshot.snapshotId,
      suppressWorkspaceFallback: true,
      config: runConfig,
    },
    cleanupBundleMcpOnRunEnd: true,
  };
  const rawAgentResult = await agentCommandFromIngress(agentOpts, defaultRuntime);
  const finalAnswer = finalAnswerFromAgentResult(rawAgentResult);
  return {
    rawAgentResult,
    result: {
      runId: ctx.runId,
      status: "succeeded",
      threadId: ctx.threadId,
      openclawSessionKey: ctx.session.sessionKey,
      workspaceDir: ctx.workspace.root,
      resolvedConfigSnapshotId: ctx.configSnapshot.snapshotId,
      session: buildEnterpriseRuntimeSessionResult({
        ctx,
        ...rawAgentSessionMeta(rawAgentResult),
      }),
      finalAnswer,
      logs: {
        eventsPath: `${ctx.dirs.runDir}/events.jsonl`,
        accessDenyPath: `${ctx.dirs.runDir}/access-deny.jsonl`,
      },
      usage: {
        provider: ctx.configSnapshot.model.provider,
        model: ctx.configSnapshot.model.model,
        authPoolId: ctx.configSnapshot.model.authPoolId,
        keyId: ctx.modelKeyLease?.keyId,
        input: ctx.configSnapshot.model.input ?? ["text"],
        attachmentCount: ctx.attachments.length,
      },
    },
  };
}
