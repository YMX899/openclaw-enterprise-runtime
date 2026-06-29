import type {
  ModelApi,
  ModelDefinitionConfig,
  ModelProviderConfig,
} from "../../config/types.models.js";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import type { ModelKeyLease } from "../model-broker/types.js";
import { resolveEnterpriseRuntimeSessionStorePath } from "../session-store.js";
import type { ResolvedRuntimeConfigSnapshot } from "./types.js";

const DEFAULT_BASE_URL: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com",
  google: "https://generativelanguage.googleapis.com/v1beta",
};

function normalizeApi(api: ResolvedRuntimeConfigSnapshot["model"]["api"]): ModelApi {
  if (api === "openai" || api === undefined) {
    return "openai-responses";
  }
  if (api === "anthropic") {
    return "anthropic-messages";
  }
  if (api === "google") {
    return "google-generative-ai";
  }
  if (api === "custom") {
    return "openai-completions";
  }
  return api;
}

function defaultBaseUrl(provider: string, api: ModelApi): string {
  const normalized = provider.trim().toLowerCase();
  if (DEFAULT_BASE_URL[normalized]) {
    return DEFAULT_BASE_URL[normalized];
  }
  if (api === "openai-completions" || api === "openai-responses") {
    return "https://api.openai.com/v1";
  }
  if (api === "anthropic-messages") {
    return "https://api.anthropic.com";
  }
  if (api === "google-generative-ai") {
    return "https://generativelanguage.googleapis.com/v1beta";
  }
  return "http://127.0.0.1:11434/v1";
}

function normalizeCost(
  cost: ResolvedRuntimeConfigSnapshot["model"]["cost"],
): ModelDefinitionConfig["cost"] {
  return {
    input: cost?.input ?? 0,
    output: cost?.output ?? 0,
    cacheRead: cost?.cacheRead ?? 0,
    cacheWrite: cost?.cacheWrite ?? 0,
  };
}

function normalizeInput(
  input: ResolvedRuntimeConfigSnapshot["model"]["input"],
): ModelDefinitionConfig["input"] {
  const values = input?.filter(
    (entry): entry is "text" | "image" | "video" | "audio" =>
      entry === "text" || entry === "image" || entry === "video" || entry === "audio",
  );
  return values?.length ? values : ["text"];
}

function normalizeReasoning(snapshot: ResolvedRuntimeConfigSnapshot): boolean {
  if (snapshot.model.reasoningEnabled !== undefined) {
    return snapshot.model.reasoningEnabled;
  }
  return snapshot.model.reasoning !== "off";
}

function modelRef(provider: string, model: string): string {
  return model.includes("/") ? model : `${provider}/${model}`;
}

function providerBaseConfigWithoutAuth(config: ModelProviderConfig | undefined) {
  if (!config) {
    return {};
  }
  const { apiKey: _apiKey, auth: _auth, headers: _headers, ...rest } = config;
  return rest;
}

export function buildEnterpriseRunOpenClawConfig(params: {
  baseConfig: OpenClawConfig;
  snapshot: ResolvedRuntimeConfigSnapshot;
  stateDir?: string;
  lease?: ModelKeyLease;
}): OpenClawConfig {
  const { baseConfig, snapshot, stateDir, lease } = params;
  const provider = snapshot.model.provider;
  const model = snapshot.model.model;
  const api = normalizeApi(snapshot.model.api);
  const baseUrl = snapshot.model.baseUrl ?? defaultBaseUrl(provider, api);
  const modelDefinition: ModelDefinitionConfig = {
    id: model,
    name: model,
    api,
    baseUrl,
    reasoning: normalizeReasoning(snapshot),
    input: normalizeInput(snapshot.model.input),
    cost: normalizeCost(snapshot.model.cost),
    contextWindow: snapshot.model.contextWindow ?? snapshot.model.contextTokens ?? 200_000,
    ...(snapshot.model.contextTokens !== undefined
      ? { contextTokens: snapshot.model.contextTokens }
      : {}),
    maxTokens:
      snapshot.model.maxTokens ?? Math.min(snapshot.model.contextWindow ?? 200_000, 16_384),
    ...(snapshot.model.params ? { params: snapshot.model.params } : {}),
    ...(snapshot.model.compat ? { compat: snapshot.model.compat } : {}),
    ...(snapshot.model.mediaInput ? { mediaInput: snapshot.model.mediaInput } : {}),
    ...(snapshot.model.headers ? { headers: snapshot.model.headers } : {}),
  };
  const providerConfig: ModelProviderConfig = {
    ...providerBaseConfigWithoutAuth(baseConfig.models?.providers?.[provider]),
    baseUrl,
    api,
    ...(lease?.secret ? { auth: "api-key" as const } : {}),
    ...(lease?.secret ? { apiKey: lease.secret } : {}),
    ...(snapshot.model.authHeader !== undefined ? { authHeader: snapshot.model.authHeader } : {}),
    ...(snapshot.model.timeoutSeconds !== undefined
      ? { timeoutSeconds: snapshot.model.timeoutSeconds }
      : {}),
    ...(snapshot.model.params ? { params: snapshot.model.params } : {}),
    ...(snapshot.model.headers ? { headers: snapshot.model.headers } : {}),
    ...(snapshot.model.request
      ? { request: snapshot.model.request as ModelProviderConfig["request"] }
      : {}),
    models: [
      modelDefinition,
      ...(baseConfig.models?.providers?.[provider]?.models ?? []).filter(
        (entry) => entry.id !== model,
      ),
    ],
  };
  const primary = modelRef(provider, model);
  return {
    ...baseConfig,
    ...(stateDir
      ? {
          session: {
            ...baseConfig.session,
            store: resolveEnterpriseRuntimeSessionStorePath(stateDir),
          },
        }
      : {}),
    models: {
      ...baseConfig.models,
      providers: {
        ...(baseConfig.models?.providers ?? {}),
        [provider]: providerConfig,
      },
    },
    agents: {
      ...baseConfig.agents,
      defaults: {
        ...baseConfig.agents?.defaults,
        skipBootstrap: true,
        model: {
          primary,
          ...(snapshot.model.fallbacks?.length ? { fallbacks: snapshot.model.fallbacks } : {}),
        },
        ...(snapshot.model.reasoning ? { reasoningDefault: snapshot.model.reasoning } : {}),
        ...(snapshot.compaction ? { compaction: snapshot.compaction } : {}),
        ...(snapshot.limits?.maxRunSeconds
          ? { timeoutSeconds: snapshot.limits.maxRunSeconds }
          : {}),
        models: {
          ...baseConfig.agents?.defaults?.models,
          [primary]: {
            ...(baseConfig.agents?.defaults?.models?.[primary] ?? {}),
            ...(snapshot.model.params ? { params: snapshot.model.params } : {}),
          },
        },
        subagents: {
          ...baseConfig.agents?.defaults?.subagents,
          delegationMode: "suggest",
          allowAgents: [],
          maxSpawnDepth: 0,
          maxChildrenPerAgent: 0,
          requireAgentId: true,
        },
      },
    },
    plugins: {
      ...baseConfig.plugins,
      ...(snapshot.plugins?.enabled?.length || snapshot.plugins?.disabled?.length
        ? {
            allow: snapshot.plugins.enabled ?? baseConfig.plugins?.allow,
            deny: snapshot.plugins.disabled ?? baseConfig.plugins?.deny,
          }
        : {}),
    },
  };
}
