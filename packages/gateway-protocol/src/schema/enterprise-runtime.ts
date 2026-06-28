import { Type, type Static } from "typebox";
import { NonEmptyString } from "./primitives.js";

const ThinkingLevelSchema = Type.Union([
  Type.Literal("off"),
  Type.Literal("minimal"),
  Type.Literal("low"),
  Type.Literal("medium"),
  Type.Literal("high"),
  Type.Literal("adaptive"),
  Type.Literal("xhigh"),
  Type.Literal("max"),
]);

const ReasoningModeSchema = Type.Union([
  Type.Literal("off"),
  Type.Literal("on"),
  Type.Literal("stream"),
]);

export const RuntimeModelOverrideSchema = Type.Object(
  {
    modelProfileId: Type.Optional(NonEmptyString),
    provider: Type.Optional(NonEmptyString),
    model: Type.Optional(NonEmptyString),
    fallbacks: Type.Optional(Type.Array(NonEmptyString)),
    authPoolId: Type.Optional(NonEmptyString),
    timeoutSeconds: Type.Optional(Type.Integer({ minimum: 0 })),
    thinking: Type.Optional(ThinkingLevelSchema),
    reasoning: Type.Optional(ReasoningModeSchema),
    maxTokens: Type.Optional(Type.Integer({ minimum: 1 })),
    params: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  },
  { additionalProperties: false },
);

export const RuntimeAttachmentSchema = Type.Object(
  {
    name: NonEmptyString,
    path: NonEmptyString,
    kind: Type.Optional(Type.String()),
  },
  { additionalProperties: false },
);

export const RuntimeRunSpecSchema = Type.Object(
  {
    runId: NonEmptyString,
    tenantId: NonEmptyString,
    userId: NonEmptyString,
    workspaceId: NonEmptyString,
    threadId: NonEmptyString,
    runtimeConfigId: NonEmptyString,
    runtimeConfigVersion: Type.Optional(NonEmptyString),
    workspace: Type.Object(
      {
        realPath: NonEmptyString,
        accessMode: Type.Union([Type.Literal("read"), Type.Literal("write")]),
      },
      { additionalProperties: false },
    ),
    productSession: Type.Object(
      {
        threadId: NonEmptyString,
        openclawSessionKey: NonEmptyString,
        metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
      },
      { additionalProperties: false },
    ),
    modelOverride: Type.Optional(RuntimeModelOverrideSchema),
    tools: Type.Optional(
      Type.Object(
        {
          profileId: Type.Optional(NonEmptyString),
          allow: Type.Optional(Type.Array(NonEmptyString)),
          deny: Type.Optional(Type.Array(NonEmptyString)),
        },
        { additionalProperties: false },
      ),
    ),
    plugins: Type.Optional(
      Type.Object(
        {
          enabled: Type.Optional(Type.Array(NonEmptyString)),
          disabled: Type.Optional(Type.Array(NonEmptyString)),
        },
        { additionalProperties: false },
      ),
    ),
    runtime: Type.Optional(
      Type.Object(
        {
          stateDir: Type.Optional(NonEmptyString),
          configPath: Type.Optional(NonEmptyString),
          logsDir: Type.Optional(NonEmptyString),
          tmpRoot: Type.Optional(NonEmptyString),
        },
        { additionalProperties: false },
      ),
    ),
    input: Type.Object(
      {
        message: NonEmptyString,
        attachments: Type.Optional(Type.Array(RuntimeAttachmentSchema)),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);

export const RuntimeQueueStateSchema = Type.Object(
  {
    queueKey: NonEmptyString,
    queuedAt: NonEmptyString,
    startedAt: Type.Optional(NonEmptyString),
    position: Type.Optional(Type.Integer({ minimum: 0 })),
  },
  { additionalProperties: false },
);

export const RuntimeRunResultSchema = Type.Object(
  {
    runId: NonEmptyString,
    status: Type.Union([
      Type.Literal("succeeded"),
      Type.Literal("failed"),
      Type.Literal("timeout"),
      Type.Literal("forbidden"),
    ]),
    threadId: NonEmptyString,
    openclawSessionKey: NonEmptyString,
    workspaceDir: NonEmptyString,
    resolvedConfigSnapshotId: NonEmptyString,
    finalAnswer: Type.Optional(Type.String()),
    queue: Type.Optional(RuntimeQueueStateSchema),
    logs: Type.Object(
      {
        eventsPath: NonEmptyString,
        accessDenyPath: Type.Optional(NonEmptyString),
        errorPath: Type.Optional(NonEmptyString),
      },
      { additionalProperties: false },
    ),
    usage: Type.Optional(
      Type.Object(
        {
          provider: Type.Optional(Type.String()),
          model: Type.Optional(Type.String()),
          authPoolId: Type.Optional(Type.String()),
          keyId: Type.Optional(Type.String()),
          inputTokens: Type.Optional(Type.Integer({ minimum: 0 })),
          outputTokens: Type.Optional(Type.Integer({ minimum: 0 })),
          estimatedCostUsd: Type.Optional(Type.Number({ minimum: 0 })),
        },
        { additionalProperties: false },
      ),
    ),
    error: Type.Optional(
      Type.Object(
        {
          code: NonEmptyString,
          message: NonEmptyString,
        },
        { additionalProperties: false },
      ),
    ),
  },
  { additionalProperties: false },
);

export type RuntimeModelOverride = Static<typeof RuntimeModelOverrideSchema>;
export type RuntimeAttachment = Static<typeof RuntimeAttachmentSchema>;
export type RuntimeRunSpec = Static<typeof RuntimeRunSpecSchema>;
export type RuntimeQueueState = Static<typeof RuntimeQueueStateSchema>;
export type RuntimeRunResult = Static<typeof RuntimeRunResultSchema>;
