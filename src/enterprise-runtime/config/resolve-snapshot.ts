import type { RuntimeRunSpec } from "../../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import { EnterpriseRuntimeError } from "../errors.js";
import { applyEnterpriseRuntimeSubagentToolPolicy } from "../subagent-policy.js";
import { objectHash } from "./hash.js";
import { assertRuntimeOverridesAllowed, stripReadModeMutatingTools } from "./override-policy.js";
import type {
  EnterpriseRuntimeConfigFile,
  ModelProfile,
  ProviderCredentialPool,
  ResolvedRuntimeConfigSnapshot,
  RuntimeConfig,
} from "./types.js";

function unique(values: Array<string | undefined>): string[] | undefined {
  const next = [...new Set(values.filter((value): value is string => Boolean(value?.trim())))];
  return next.length ? next : undefined;
}

function findRuntimeConfig(file: EnterpriseRuntimeConfigFile, id: string): RuntimeConfig {
  const config = file.runtimeConfigs.find((entry) => entry.id === id);
  if (!config) {
    throw new EnterpriseRuntimeError("RUNTIME_CONFIG_NOT_FOUND", `runtime config not found: ${id}`);
  }
  return config;
}

function findModelProfile(file: EnterpriseRuntimeConfigFile, id: string): ModelProfile {
  const profile = file.modelProfiles.find((entry) => entry.id === id);
  if (!profile) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_MODEL_PROFILE_NOT_FOUND",
      `model profile not found: ${id}`,
    );
  }
  return profile;
}

function findPool(file: EnterpriseRuntimeConfigFile, id: string): ProviderCredentialPool {
  const pool = file.credentialPools?.find((entry) => entry.id === id);
  if (!pool) {
    throw new EnterpriseRuntimeError(
      "MODEL_KEY_POOL_EXHAUSTED",
      `credential pool not found: ${id}`,
    );
  }
  return pool;
}

function requireAuthPoolId(id: string | undefined): string {
  const authPoolId = id?.trim();
  if (!authPoolId) {
    throw new EnterpriseRuntimeError(
      "MODEL_KEY_POOL_EXHAUSTED",
      "model authPoolId is required for enterprise runtime runs",
    );
  }
  return authPoolId;
}

export function resolveRuntimeConfigSnapshot(params: {
  configFile: EnterpriseRuntimeConfigFile;
  spec: RuntimeRunSpec;
}): { runtimeConfig: RuntimeConfig; snapshot: ResolvedRuntimeConfigSnapshot } {
  const { spec, configFile } = params;
  const runtimeConfig = findRuntimeConfig(configFile, spec.runtimeConfigId);
  if (spec.runtimeConfigVersion && runtimeConfig.version !== spec.runtimeConfigVersion) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_CONFIG_VERSION_MISMATCH",
      `runtime config version mismatch: expected ${spec.runtimeConfigVersion}, got ${runtimeConfig.version ?? "(none)"}`,
    );
  }
  assertRuntimeOverridesAllowed(runtimeConfig, spec);
  const modelProfileId = spec.modelOverride?.modelProfileId ?? runtimeConfig.model.modelProfileId;
  const profile = findModelProfile(configFile, modelProfileId);
  const model = {
    modelProfileId,
    provider: spec.modelOverride?.provider ?? runtimeConfig.model.provider ?? profile.provider,
    model: spec.modelOverride?.model ?? runtimeConfig.model.model ?? profile.model,
    api: profile.api,
    baseUrl: profile.baseUrl,
    authPoolId:
      spec.modelOverride?.authPoolId ?? runtimeConfig.model.authPoolId ?? profile.authPoolId,
    fallbacks: spec.modelOverride?.fallbacks ?? runtimeConfig.model.fallbacks ?? profile.fallbacks,
    thinking: spec.modelOverride?.thinking ?? runtimeConfig.model.thinking ?? profile.thinking,
    reasoning: spec.modelOverride?.reasoning ?? runtimeConfig.model.reasoning ?? profile.reasoning,
    contextWindow: profile.contextWindow,
    contextTokens: profile.contextTokens,
    maxTokens: spec.modelOverride?.maxTokens ?? runtimeConfig.model.maxTokens ?? profile.maxTokens,
    maxTokensField: profile.maxTokensField,
    timeoutSeconds:
      spec.modelOverride?.timeoutSeconds ??
      runtimeConfig.model.timeoutSeconds ??
      profile.timeoutSeconds,
    params: {
      ...(profile.params ?? {}),
      ...(runtimeConfig.model.params ?? {}),
      ...(spec.modelOverride?.params ?? {}),
    },
    reasoningEnabled: profile.reasoningEnabled,
    input: profile.input,
    cost: profile.cost,
    compat: profile.compat,
    mediaInput: profile.mediaInput,
    headers: profile.headers,
    authHeader: profile.authHeader,
    request: profile.request,
  };
  model.authPoolId = requireAuthPoolId(model.authPoolId);
  const pool = findPool(configFile, model.authPoolId);
  const toolsAllow = unique([...(runtimeConfig.tools?.allow ?? []), ...(spec.tools?.allow ?? [])]);
  const toolsDeny = unique([...(runtimeConfig.tools?.deny ?? []), ...(spec.tools?.deny ?? [])]);
  const tools = applyEnterpriseRuntimeSubagentToolPolicy({
    allow:
      spec.workspace.accessMode === "read" ? stripReadModeMutatingTools(toolsAllow) : toolsAllow,
    deny: toolsDeny,
  });
  const snapshot: ResolvedRuntimeConfigSnapshot = {
    snapshotId: `${spec.runId}-${objectHash({ runId: spec.runId, runtimeConfig, profile, spec }).slice(0, 12)}`,
    runId: spec.runId,
    createdAt: new Date().toISOString(),
    runtimeConfigId: runtimeConfig.id,
    runtimeConfigVersion: runtimeConfig.version,
    model,
    tools,
    plugins: {
      enabled: unique([
        ...(runtimeConfig.plugins?.enabled ?? []),
        ...(spec.plugins?.enabled ?? []),
      ]),
      disabled: unique([
        ...(runtimeConfig.plugins?.disabled ?? []),
        ...(spec.plugins?.disabled ?? []),
      ]),
    },
    prompt: runtimeConfig.prompt,
    compaction: runtimeConfig.compaction,
    limits: runtimeConfig.limits,
    sourceRefs: {
      runtimeConfigHash: objectHash(runtimeConfig),
      modelProfileHash: objectHash(profile),
      credentialPoolHash: pool ? objectHash(pool) : undefined,
    },
  };
  return { runtimeConfig, snapshot };
}
