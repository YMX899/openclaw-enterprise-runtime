type Tail = Promise<void>;

const sessionLocks = new Map<string, Tail>();

async function waitForTail(tail: Tail | undefined) {
  if (!tail) {
    return;
  }
  try {
    await tail;
  } catch {
    // Preserve FIFO progress after a failed run.
  }
}

export async function runWithSessionLock<T>(lockKey: string, fn: () => Promise<T>): Promise<T> {
  const previous = sessionLocks.get(lockKey);
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
  sessionLocks.set(lockKey, chained);
  await waitForTail(previous);
  try {
    return await fn();
  } finally {
    release();
    if (sessionLocks.get(lockKey) === chained) {
      sessionLocks.delete(lockKey);
    }
  }
}

export function buildEnterpriseSessionLockKey(namespace: string, sessionKey: string): string {
  return `${namespace}\0${sessionKey}`;
}

export function getSessionLockSizeForTest(): number {
  return sessionLocks.size;
}
