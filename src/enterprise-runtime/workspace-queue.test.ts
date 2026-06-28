import { describe, expect, it } from "vitest";
import { getWorkspaceQueueSizeForTest, runWithWorkspaceQueue } from "./workspace-queue.js";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("runWithWorkspaceQueue", () => {
  it("runs same-workspace jobs FIFO and clears chained queue state", async () => {
    const gate = deferred();
    const order: string[] = [];
    const first = runWithWorkspaceQueue("workspace-a", async () => {
      order.push("first:start");
      await gate.promise;
      order.push("first:end");
      return "first";
    });
    const second = runWithWorkspaceQueue("workspace-a", async () => {
      order.push("second:start");
      return "second";
    });

    await Promise.resolve();
    expect(order).toEqual(["first:start"]);
    expect(getWorkspaceQueueSizeForTest()).toBe(1);

    gate.resolve();
    await expect(first).resolves.toMatchObject({ result: "first" });
    await expect(second).resolves.toMatchObject({ result: "second" });
    expect(order).toEqual(["first:start", "first:end", "second:start"]);
    expect(getWorkspaceQueueSizeForTest()).toBe(0);
  });

  it("does not block different workspaces", async () => {
    const gate = deferred();
    const order: string[] = [];
    const first = runWithWorkspaceQueue("workspace-a", async () => {
      order.push("a:start");
      await gate.promise;
      return "a";
    });
    const second = runWithWorkspaceQueue("workspace-b", async () => {
      order.push("b:start");
      return "b";
    });

    await expect(second).resolves.toMatchObject({ result: "b" });
    expect(order).toEqual(["a:start", "b:start"]);
    gate.resolve();
    await first;
    expect(getWorkspaceQueueSizeForTest()).toBe(0);
  });
});
