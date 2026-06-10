import { normalizeUniqueStringEntries } from "@openclaw/normalization-core/string-normalization";
import { sleepWithAbort } from "../infra/backoff.js";
import { formatErrorMessage } from "../infra/errors.js";
import {
  resolveTransientProviderAttempts,
  resolveTransientProviderDelayMs,
  resolveTransientProviderRetryOptions,
  shouldRetrySameKeyProviderOperation,
  type TransientProviderRetryConfig,
} from "../provider-runtime/operation-retry.js";
import { collectProviderApiKeys, isApiKeyRateLimitError } from "./live-auth-keys.js";

// API-key rotation wrapper for provider calls. It tries configured keys in order
// on rate-limit-like failures and can also retry transient errors on the same key.
type ApiKeyRetryParams = {
  apiKey: string;
  error: unknown;
  attempt: number;
};

type ExecuteWithApiKeyRotationOptions<T> = {
  provider: string;
  apiKeys: string[];
  execute: (apiKey: string) => Promise<T>;
  shouldRetry?: (params: ApiKeyRetryParams & { message: string }) => boolean;
  onRetry?: (params: ApiKeyRetryParams & { message: string }) => void;
  transientRetry?: TransientProviderRetryConfig;
};

type ProviderApiKeyPoolEntry = {
  cooldownUntil?: number;
  rateLimitCount: number;
  lastRateLimitedAt?: number;
  lastSelectedAt?: number;
};

type ProviderApiKeyPool = {
  cursor: number;
  entries: Map<string, ProviderApiKeyPoolEntry>;
};

export type ProviderApiKeyPoolSnapshotEntry = {
  index: number;
  cooldownUntil?: number;
  rateLimitCount: number;
  available: boolean;
};

const DEFAULT_API_KEY_POOL_RATE_LIMIT_COOLDOWN_MS = 60_000;
const API_KEY_POOL_RATE_LIMIT_COOLDOWN_ENV = "OPENCLAW_API_KEY_POOL_RATE_LIMIT_COOLDOWN_MS";
const providerApiKeyPools = new Map<string, ProviderApiKeyPool>();

function dedupeApiKeys(raw: string[]): string[] {
  return normalizeUniqueStringEntries(raw);
}

function normalizePoolProvider(provider: string): string {
  return provider.trim().toLowerCase() || "unknown";
}

function getProviderApiKeyPool(provider: string): ProviderApiKeyPool {
  const key = normalizePoolProvider(provider);
  let pool = providerApiKeyPools.get(key);
  if (!pool) {
    pool = { cursor: 0, entries: new Map() };
    providerApiKeyPools.set(key, pool);
  }
  return pool;
}

function resolveApiKeyPoolCooldownMs(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env[API_KEY_POOL_RATE_LIMIT_COOLDOWN_ENV]?.trim();
  if (!raw) {
    return DEFAULT_API_KEY_POOL_RATE_LIMIT_COOLDOWN_MS;
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return DEFAULT_API_KEY_POOL_RATE_LIMIT_COOLDOWN_MS;
  }
  return Math.floor(parsed);
}

function syncProviderApiKeyPool(pool: ProviderApiKeyPool, keys: string[]): void {
  const active = new Set(keys);
  for (const key of keys) {
    if (!pool.entries.has(key)) {
      pool.entries.set(key, { rateLimitCount: 0 });
    }
  }
  for (const key of pool.entries.keys()) {
    if (!active.has(key)) {
      pool.entries.delete(key);
    }
  }
  if (pool.cursor >= keys.length) {
    pool.cursor = 0;
  }
}

function isApiKeyCoolingDown(entry: ProviderApiKeyPoolEntry | undefined, now: number): boolean {
  if (!entry?.cooldownUntil) {
    return false;
  }
  if (entry.cooldownUntil <= now) {
    entry.cooldownUntil = undefined;
    return false;
  }
  return true;
}

function compareCooldownSoonest(
  a: { key: string; index: number; entry: ProviderApiKeyPoolEntry },
  b: { key: string; index: number; entry: ProviderApiKeyPoolEntry },
): number {
  const aUntil = a.entry.cooldownUntil ?? Number.POSITIVE_INFINITY;
  const bUntil = b.entry.cooldownUntil ?? Number.POSITIVE_INFINITY;
  if (aUntil !== bUntil) {
    return aUntil - bUntil;
  }
  return a.index - b.index;
}

function resolveProviderApiKeyPoolOrder(params: {
  provider: string;
  apiKeys: string[];
  now?: number;
  allowCoolingFallback?: boolean;
}): string[] {
  const keys = dedupeApiKeys(params.apiKeys);
  if (keys.length <= 1) {
    return keys;
  }
  const now = params.now ?? Date.now();
  const pool = getProviderApiKeyPool(params.provider);
  syncProviderApiKeyPool(pool, keys);

  const available: string[] = [];
  const cooling: Array<{ key: string; index: number; entry: ProviderApiKeyPoolEntry }> = [];
  for (let offset = 0; offset < keys.length; offset += 1) {
    const index = (pool.cursor + offset) % keys.length;
    const key = keys[index];
    const entry = pool.entries.get(key);
    if (isApiKeyCoolingDown(entry, now)) {
      cooling.push({ key, index, entry: entry ?? { rateLimitCount: 0 } });
    } else {
      available.push(key);
    }
  }
  cooling.sort(compareCooldownSoonest);
  if (available.length === 0 && params.allowCoolingFallback === false) {
    return [];
  }
  return [...available, ...cooling.map((entry) => entry.key)];
}

export function selectProviderApiKeyFromPool(params: {
  provider: string;
  apiKeys: string[];
  now?: number;
  allowCoolingFallback?: boolean;
}): string | undefined {
  const ordered = resolveProviderApiKeyPoolOrder(params);
  const selected = ordered[0];
  if (!selected) {
    return undefined;
  }
  const keys = dedupeApiKeys(params.apiKeys);
  const selectedIndex = keys.indexOf(selected);
  const pool = getProviderApiKeyPool(params.provider);
  pool.cursor = selectedIndex >= 0 ? (selectedIndex + 1) % keys.length : pool.cursor;
  const entry = pool.entries.get(selected);
  if (entry) {
    entry.lastSelectedAt = params.now ?? Date.now();
  }
  return selected;
}

export function markProviderApiKeyRateLimited(params: {
  provider: string;
  apiKey?: string;
  cooldownMs?: number;
  now?: number;
}): void {
  const apiKey = params.apiKey?.trim();
  if (!apiKey) {
    return;
  }
  const now = params.now ?? Date.now();
  const cooldownMs = params.cooldownMs ?? resolveApiKeyPoolCooldownMs();
  const pool = getProviderApiKeyPool(params.provider);
  const entry = pool.entries.get(apiKey) ?? { rateLimitCount: 0 };
  entry.rateLimitCount += 1;
  entry.lastRateLimitedAt = now;
  entry.cooldownUntil = cooldownMs > 0 ? now + cooldownMs : now;
  pool.entries.set(apiKey, entry);
}

export function getProviderApiKeyPoolSnapshot(params: {
  provider: string;
  apiKeys: string[];
  now?: number;
}): ProviderApiKeyPoolSnapshotEntry[] {
  const keys = dedupeApiKeys(params.apiKeys);
  const now = params.now ?? Date.now();
  const pool = getProviderApiKeyPool(params.provider);
  syncProviderApiKeyPool(pool, keys);
  return keys.map((key, index) => {
    const entry = pool.entries.get(key) ?? { rateLimitCount: 0 };
    const available = !isApiKeyCoolingDown(entry, now);
    return {
      index,
      ...(entry.cooldownUntil ? { cooldownUntil: entry.cooldownUntil } : {}),
      rateLimitCount: entry.rateLimitCount,
      available,
    };
  });
}

export function resetProviderApiKeyPoolsForTest(): void {
  providerApiKeyPools.clear();
}

/** Collect primary and live-discovered provider keys in stable de-duped order. */
export function collectProviderApiKeysForExecution(params: {
  provider: string;
  primaryApiKey?: string;
}): string[] {
  const { primaryApiKey, provider } = params;
  return dedupeApiKeys([primaryApiKey?.trim() ?? "", ...collectProviderApiKeys(provider)]);
}

/**
 * Execute a provider operation with key rotation and optional same-key transient
 * retries.
 */
export async function executeWithApiKeyRotation<T>(
  params: ExecuteWithApiKeyRotationOptions<T>,
): Promise<T> {
  const keys = dedupeApiKeys(params.apiKeys);
  if (keys.length === 0) {
    throw new Error(`No API keys configured for provider "${params.provider}".`);
  }

  let lastError: unknown;
  const transientRetry = resolveTransientProviderRetryOptions(params.transientRetry);
  const orderedKeys = resolveProviderApiKeyPoolOrder({ provider: params.provider, apiKeys: keys });
  keyLoop: for (let apiKeyIndex = 0; apiKeyIndex < orderedKeys.length; apiKeyIndex += 1) {
    const apiKey = orderedKeys[apiKeyIndex];
    const maxOperationAttempts = resolveTransientProviderAttempts(transientRetry);
    for (let attemptNumber = 1; attemptNumber <= maxOperationAttempts; attemptNumber += 1) {
      try {
        const result = await params.execute(apiKey);
        selectProviderApiKeyFromPool({ provider: params.provider, apiKeys: keys });
        return result;
      } catch (error) {
        lastError = error;
        const message = formatErrorMessage(error);
        const rotateKey = params.shouldRetry
          ? params.shouldRetry({ apiKey, error, attempt: apiKeyIndex, message })
          : isApiKeyRateLimitError(message);

        if (rotateKey) {
          markProviderApiKeyRateLimited({ provider: params.provider, apiKey });
          // A rotation signal consumes the current key and moves to the next key
          // without running same-key transient retry logic.
          if (apiKeyIndex + 1 >= orderedKeys.length) {
            break;
          }
          params.onRetry?.({ apiKey, error, attempt: apiKeyIndex, message });
          break;
        }

        if (
          !transientRetry ||
          !shouldRetrySameKeyProviderOperation({
            options: transientRetry,
            error,
            message,
            provider: params.provider,
            apiKeyIndex,
            attemptNumber,
            maxAttempts: maxOperationAttempts,
          })
        ) {
          break keyLoop;
        }

        const delayMs = resolveTransientProviderDelayMs(transientRetry, attemptNumber);
        // Same-key transient retries are bounded by provider policy and keep the
        // current key stable so auth rotation only handles key-specific failures.
        const sleep = transientRetry.sleep ?? sleepWithAbort;
        await sleep(delayMs, transientRetry.signal);
      }
    }
  }

  if (lastError === undefined) {
    throw new Error(`Failed to run API request for ${params.provider}.`);
  }
  throw toLintErrorObject(lastError, "Non-Error thrown");
}

function toLintErrorObject(value: unknown, fallbackMessage: string): Error {
  // Preserve thrown object properties for callers/tests while still satisfying
  // Error-only throw lint expectations.
  if (value instanceof Error) {
    return value;
  }
  if (typeof value === "string") {
    return new Error(value);
  }
  const error = new Error(fallbackMessage, { cause: value });
  if ((typeof value === "object" && value !== null) || typeof value === "function") {
    Object.assign(error, value);
  }
  return error;
}
