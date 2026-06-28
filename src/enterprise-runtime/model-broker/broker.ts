import { setTimeout as sleep } from "node:timers/promises";
import type { ProviderCredentialPool } from "../config/types.js";
import { resolveSecretRef } from "./credential-pool.js";
import { ModelKeyPoolError } from "./errors.js";
import type { ModelKeyBrokerAcquireParams, ModelKeyLease } from "./types.js";

type KeyState = {
  inFlight: number;
  cooldownUntil: number;
  disabled: boolean;
};

const states = new Map<string, KeyState>();
const roundRobin = new Map<string, number>();

function stateFor(poolId: string, keyId: string): KeyState {
  const id = `${poolId}\0${keyId}`;
  let state = states.get(id);
  if (!state) {
    state = { inFlight: 0, cooldownUntil: 0, disabled: false };
    states.set(id, state);
  }
  return state;
}

function normalizeProvider(value: string): string {
  return value.trim().toLowerCase();
}

function findPool(pools: ProviderCredentialPool[] | undefined, id: string): ProviderCredentialPool {
  const pool = pools?.find((entry) => entry.id === id);
  if (!pool) {
    throw new ModelKeyPoolError("MODEL_KEY_POOL_EXHAUSTED", `credential pool not found: ${id}`);
  }
  return pool;
}

function supportsModel(key: ProviderCredentialPool["keys"][number], model: string): boolean {
  return !key.models?.length || key.models.includes(model);
}

function pickKey(pool: ProviderCredentialPool, model: string) {
  const now = Date.now();
  const candidates = pool.keys
    .map((key) => ({ key, state: stateFor(pool.id, key.keyId) }))
    .filter(({ key, state }) => {
      const maxConcurrent = key.maxConcurrent ?? 1;
      return (
        !key.disabled &&
        !state.disabled &&
        state.cooldownUntil <= now &&
        state.inFlight < maxConcurrent &&
        supportsModel(key, model)
      );
    });
  if (!candidates.length) {
    return undefined;
  }
  if (pool.strategy === "round_robin" || pool.strategy === "weighted_round_robin") {
    const weighted = candidates.flatMap((candidate) =>
      Array(Math.max(1, Math.floor(candidate.key.weight ?? 1))).fill(candidate),
    );
    const index = roundRobin.get(pool.id) ?? 0;
    roundRobin.set(pool.id, index + 1);
    return weighted[index % weighted.length];
  }
  candidates.sort(
    (left, right) =>
      left.state.inFlight - right.state.inFlight ||
      (right.key.weight ?? 1) - (left.key.weight ?? 1) ||
      left.key.keyId.localeCompare(right.key.keyId),
  );
  return candidates[0];
}

function cooldownMs(pool: ProviderCredentialPool, errorClass: string | undefined): number {
  if (errorClass === "rate_limit") {
    return pool.cooldown?.rateLimitMs ?? 60_000;
  }
  if (errorClass === "quota_exhausted") {
    return pool.cooldown?.quotaMs ?? 3_600_000;
  }
  if (errorClass === "overloaded") {
    return pool.cooldown?.overloadedMs ?? 15_000;
  }
  return 0;
}

export async function acquireModelKeyLease(
  params: ModelKeyBrokerAcquireParams,
): Promise<ModelKeyLease | undefined> {
  if (!params.authPoolId) {
    return undefined;
  }
  const pool = findPool(params.pools, params.authPoolId);
  if (normalizeProvider(pool.provider) !== normalizeProvider(params.provider)) {
    throw new ModelKeyPoolError(
      "MODEL_KEY_POOL_EXHAUSTED",
      `credential pool ${pool.id} belongs to provider ${pool.provider}, not ${params.provider}`,
    );
  }
  const deadline = Date.now() + (pool.acquireTimeoutMs ?? 30_000);
  while (true) {
    if (params.signal?.aborted) {
      throw new ModelKeyPoolError(
        "MODEL_KEY_POOL_BUSY",
        `credential pool wait aborted: ${pool.id}`,
      );
    }
    const selected = pickKey(pool, params.model);
    if (selected) {
      selected.state.inFlight += 1;
      let released = false;
      const release = (errorClass?: string) => {
        if (released) {
          return;
        }
        released = true;
        selected.state.inFlight = Math.max(0, selected.state.inFlight - 1);
        if (errorClass === "auth_error" && pool.cooldown?.authErrorDisablesKey !== false) {
          selected.state.disabled = true;
          return;
        }
        const ms = cooldownMs(pool, errorClass);
        if (ms > 0) {
          selected.state.cooldownUntil = Date.now() + ms;
        }
      };
      try {
        return {
          authPoolId: pool.id,
          keyId: selected.key.keyId,
          secret: resolveSecretRef(selected.key.secretRef),
          release,
        };
      } catch (error) {
        release("auth_error");
        throw error;
      }
    }
    if (Date.now() >= deadline) {
      throw new ModelKeyPoolError(
        "MODEL_KEY_POOL_BUSY",
        `no available key in credential pool ${pool.id} for ${params.provider}/${params.model}`,
      );
    }
    await sleep(100, undefined, { signal: params.signal }).catch(() => {
      throw new ModelKeyPoolError(
        "MODEL_KEY_POOL_BUSY",
        `credential pool wait aborted: ${pool.id}`,
      );
    });
  }
}

export const testing = {
  stateFor,
  states,
  roundRobin,
};
