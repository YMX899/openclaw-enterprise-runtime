import type { RuntimeQueueState } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";

type Tail = Promise<void>;

const workspaceQueues = new Map<string, Tail>();

async function waitForTail(tail: Tail | undefined) {
  if (!tail) {
    return;
  }
  try {
    await tail;
  } catch {
    // The next queued run should not inherit the previous run failure.
  }
}

export async function runWithWorkspaceQueue<T>(
  queueKey: string,
  fn: (queue: RuntimeQueueState) => Promise<T>,
): Promise<{ result: T; queue: RuntimeQueueState }> {
  const queuedAt = new Date().toISOString();
  const previous = workspaceQueues.get(queueKey);
  let release!: () => void;
  const current = new Promise<void>((resolve) => {
    release = resolve;
  });
  const chained = previous
    ? previous.then(
        () => current,
        () => current,
      )
    : current;
  workspaceQueues.set(queueKey, chained);
  await waitForTail(previous);
  const queue: RuntimeQueueState = {
    queueKey,
    queuedAt,
    startedAt: new Date().toISOString(),
  };
  try {
    return { result: await fn(queue), queue };
  } finally {
    release();
    if (workspaceQueues.get(queueKey) === chained) {
      workspaceQueues.delete(queueKey);
    }
  }
}

export function getWorkspaceQueueSizeForTest(): number {
  return workspaceQueues.size;
}
