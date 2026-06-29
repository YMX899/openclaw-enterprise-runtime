import type { RuntimeModelOverride } from "../../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import type {
  ModelApi,
  ModelCompatConfig,
  ModelImageInputConfig,
  ModelProviderConfig,
} from "../../config/types.models.js";

export type RuntimeConfig = {
  id: string;
  version?: string;
  stateDir?: string;
  logsDir?: string;
  tmpRoot?: string;
  sessionStoreId?: string;
  artifactStoreId?: string;
  model: RuntimeModelOverride & {
    modelProfileId: string;
  };
  tools?: {
    allow?: string[];
    deny?: string[];
  };
  plugins?: {
    enabled?: string[];
    disabled?: string[];
  };
  prompt?: {
    mode?: "full" | "minimal" | "none";
    extraSystemPrompt?: string;
  };
  compaction?: {
    enabled?: boolean;
    reserveTokens?: number;
  };
  limits?: {
    maxRunSeconds?: number;
    maxToolCalls?: number;
  };
  overridePolicy?: RuntimeOverridePolicy;
};

export type RuntimeOverridePolicy = {
  model?: {
    allowedFields?: Array<keyof RuntimeModelOverride>;
    allowedProviders?: string[];
    allowedModels?: string[];
    allowedModelProfileIds?: string[];
    allowedAuthPoolIds?: string[];
    allowedThinking?: string[];
    maxTimeoutSeconds?: number;
    maxTokens?: number;
    allowParams?: string[];
  };
  tools?: {
    allowRuntimeAllowList?: boolean;
    allowRuntimeDenyList?: boolean;
    allowedToolNames?: string[];
  };
  plugins?: {
    allowEnable?: boolean;
    allowDisable?: boolean;
    allowedPluginIds?: string[];
  };
};

export type ModelProfile = RuntimeModelOverride & {
  id: string;
  provider: string;
  model: string;
  api?: ModelApi | "openai" | "anthropic" | "google" | "custom";
  baseUrl?: string;
  contextWindow?: number;
  contextTokens?: number;
  maxTokensField?: string;
  reasoningEnabled?: boolean;
  input?: Array<"text" | "image" | "video" | "audio">;
  cost?: {
    input?: number;
    output?: number;
    cacheRead?: number;
    cacheWrite?: number;
  };
  compat?: ModelCompatConfig;
  mediaInput?: {
    image?: ModelImageInputConfig;
  };
  headers?: Record<string, string>;
  authHeader?: boolean;
  request?: ModelProviderConfig["request"];
};

export type ProviderCredentialPool = {
  id: string;
  provider: string;
  strategy?: "least_busy" | "round_robin" | "weighted_round_robin";
  acquireTimeoutMs?: number;
  keys: Array<{
    keyId: string;
    secretRef: string;
    models?: string[];
    weight?: number;
    maxConcurrent?: number;
    requestsPerMinute?: number;
    tokensPerMinute?: number;
    disabled?: boolean;
  }>;
  cooldown?: {
    rateLimitMs?: number;
    overloadedMs?: number;
    quotaMs?: number;
    authErrorDisablesKey?: boolean;
  };
  retry?: {
    maxAttempts?: number;
    retryOn?: string[];
  };
};

export type RuntimeSessionStoreConfig =
  | {
      id: string;
      type: "file";
      rootDir: string;
      namespace?: string;
      maxSessionBytes?: number;
      retentionDays?: number;
    }
  | {
      id: string;
      type: "database";
      namespace?: string;
      connectionRef: string;
      tablePrefix?: string;
      maxSessionBytes?: number;
      retentionDays?: number;
    }
  | {
      id: string;
      type: "db-object";
      namespace?: string;
      connectionRef: string;
      objectBucketRef: string;
      objectPrefix?: string;
      chunkBytes?: number;
      maxSessionBytes?: number;
      retentionDays?: number;
    };

export type RuntimeArtifactStoreConfig =
  | {
      id: string;
      type: "file";
      logsDir: string;
      tmpRoot: string;
      snapshotDir?: string;
      retentionDays?: number;
    }
  | {
      id: string;
      type: "object";
      bucketRef: string;
      prefix?: string;
      localCacheDir: string;
      retentionDays?: number;
    };

export type EnterpriseRuntimeConfigFile = {
  runtimeConfigs: RuntimeConfig[];
  modelProfiles: ModelProfile[];
  credentialPools?: ProviderCredentialPool[];
  sessionStores?: RuntimeSessionStoreConfig[];
  artifactStores?: RuntimeArtifactStoreConfig[];
};

export type ResolvedRuntimeConfigSnapshot = {
  snapshotId: string;
  runId: string;
  createdAt: string;
  runtimeConfigId: string;
  runtimeConfigVersion?: string;
  model: {
    modelProfileId?: string;
    provider: string;
    model: string;
    api?: ModelProfile["api"];
    baseUrl?: string;
    authPoolId?: string;
    fallbacks?: string[];
    thinking?: RuntimeModelOverride["thinking"];
    reasoning?: RuntimeModelOverride["reasoning"];
    contextWindow?: number;
    contextTokens?: number;
    maxTokens?: number;
    maxTokensField?: string;
    timeoutSeconds?: number;
    params?: Record<string, unknown>;
    reasoningEnabled?: boolean;
    input?: ModelProfile["input"];
    cost?: ModelProfile["cost"];
    compat?: ModelProfile["compat"];
    mediaInput?: ModelProfile["mediaInput"];
    headers?: ModelProfile["headers"];
    authHeader?: boolean;
    request?: ModelProfile["request"];
  };
  tools: {
    allow?: string[];
    deny?: string[];
  };
  plugins?: RuntimeConfig["plugins"];
  prompt?: RuntimeConfig["prompt"];
  compaction?: RuntimeConfig["compaction"];
  limits?: RuntimeConfig["limits"];
  sourceRefs: {
    runtimeConfigHash: string;
    modelProfileHash?: string;
    credentialPoolHash?: string;
    openclawBaseConfigHash?: string;
  };
};
