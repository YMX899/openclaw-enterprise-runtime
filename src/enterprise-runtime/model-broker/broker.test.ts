import { afterEach, describe, expect, it } from "vitest";
import type { ProviderCredentialPool } from "../config/types.js";
import { acquireModelKeyLease, testing } from "./broker.js";

function pool(): ProviderCredentialPool {
  return {
    id: "pool-1",
    provider: "openai",
    acquireTimeoutMs: 20,
    keys: [
      {
        keyId: "key-1",
        secretRef: "env:OPENCLAW_TEST_KEY_1",
        models: ["gpt-5"],
        maxConcurrent: 1,
      },
      {
        keyId: "key-2",
        secretRef: "env:OPENCLAW_TEST_KEY_2",
        models: ["gpt-5"],
        maxConcurrent: 1,
      },
    ],
    cooldown: {
      rateLimitMs: 1000,
      authErrorDisablesKey: true,
    },
  };
}

describe("enterprise model key broker", () => {
  afterEach(() => {
    delete process.env.OPENCLAW_TEST_KEY_1;
    delete process.env.OPENCLAW_TEST_KEY_2;
    testing.states.clear();
    testing.roundRobin.clear();
  });

  it("leases distinct keys until pool concurrency is exhausted", async () => {
    process.env.OPENCLAW_TEST_KEY_1 = "secret-1";
    process.env.OPENCLAW_TEST_KEY_2 = "secret-2";

    const first = await acquireModelKeyLease({
      pools: [pool()],
      authPoolId: "pool-1",
      provider: "openai",
      model: "gpt-5",
    });
    const second = await acquireModelKeyLease({
      pools: [pool()],
      authPoolId: "pool-1",
      provider: "openai",
      model: "gpt-5",
    });

    expect(first?.keyId).toBe("key-1");
    expect(second?.keyId).toBe("key-2");
    await expect(
      acquireModelKeyLease({
        pools: [pool()],
        authPoolId: "pool-1",
        provider: "openai",
        model: "gpt-5",
      }),
    ).rejects.toMatchObject({ code: "MODEL_KEY_POOL_BUSY" });

    first?.release();
    const third = await acquireModelKeyLease({
      pools: [pool()],
      authPoolId: "pool-1",
      provider: "openai",
      model: "gpt-5",
    });
    expect(third?.keyId).toBe("key-1");
    second?.release();
    third?.release();
  });

  it("cooldowns rate-limited keys and disables auth-failed keys", async () => {
    process.env.OPENCLAW_TEST_KEY_1 = "secret-1";
    process.env.OPENCLAW_TEST_KEY_2 = "secret-2";

    const first = await acquireModelKeyLease({
      pools: [pool()],
      authPoolId: "pool-1",
      provider: "openai",
      model: "gpt-5",
    });
    first?.release("rate_limit");

    const second = await acquireModelKeyLease({
      pools: [pool()],
      authPoolId: "pool-1",
      provider: "openai",
      model: "gpt-5",
    });
    expect(second?.keyId).toBe("key-2");
    second?.release("auth_error");

    await expect(
      acquireModelKeyLease({
        pools: [pool()],
        authPoolId: "pool-1",
        provider: "openai",
        model: "gpt-5",
      }),
    ).rejects.toMatchObject({ code: "MODEL_KEY_POOL_BUSY" });
  });
});
