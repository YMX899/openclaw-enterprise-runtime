import { describe, expect, it } from "vitest";
import {
  buildEnterpriseSessionLockKey,
  getSessionLockSizeForTest,
  runWithSessionLock,
} from "./session-lock.js";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("runWithSessionLock", () => {
  it("serializes same-session runs and clears chained lock state", async () => {
    const gate = deferred();
    const order: string[] = [];
    const key = buildEnterpriseSessionLockKey("enterprise-runtime", "thread-1");
    const first = runWithSessionLock(key, async () => {
      order.push("first:start");
      await gate.promise;
      order.push("first:end");
      return "first";
    });
    const second = runWithSessionLock(key, async () => {
      order.push("second:start");
      return "second";
    });

    await Promise.resolve();
    expect(order).toEqual(["first:start"]);
    expect(getSessionLockSizeForTest()).toBe(1);

    gate.resolve();
    await expect(first).resolves.toBe("first");
    await expect(second).resolves.toBe("second");
    expect(order).toEqual(["first:start", "first:end", "second:start"]);
    expect(getSessionLockSizeForTest()).toBe(0);
  });

  it("does not block different sessions", async () => {
    const gate = deferred();
    const order: string[] = [];
    const first = runWithSessionLock("enterprise-runtime\0thread-a", async () => {
      order.push("a:start");
      await gate.promise;
      return "a";
    });
    const second = runWithSessionLock("enterprise-runtime\0thread-b", async () => {
      order.push("b:start");
      return "b";
    });

    await expect(second).resolves.toBe("b");
    expect(order).toEqual(["a:start", "b:start"]);
    gate.resolve();
    await first;
    expect(getSessionLockSizeForTest()).toBe(0);
  });
});
