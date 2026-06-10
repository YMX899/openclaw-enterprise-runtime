import fs from "node:fs/promises";
import { createServer } from "node:http";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { Readable } from "node:stream";
import { clearConfigCache, clearRuntimeConfigSnapshot } from "../../src/config/config.js";
import { clearSessionStoreCacheForTest } from "../../src/config/sessions/store.js";
import { DEFAULT_SUBAGENT_MAX_CONCURRENT } from "../../src/config/agent-limits.js";
import { startGatewayServer } from "../../src/gateway/server.js";
import { GatewayClient } from "../../src/gateway/client.js";
import { clearGatewaySubagentRuntime } from "../../src/plugins/runtime/index.js";
import { clearAllBootstrapSnapshots } from "../../src/agents/bootstrap-cache.js";
import { resetAgentRunContextForTest } from "../../src/infra/agent-events.js";

type AgentResult = {
  runId?: string;
  status?: string;
  summary?: string;
  error?: unknown;
};

type FetchStats = {
  totalRequests: number;
  activeRequests: number;
  peakActive: number;
  paths: Record<string, number>;
  statuses?: Record<string, number>;
  upstreamRequests?: number;
  upstreamActiveRequests?: number;
  upstreamPeakActive?: number;
  upstreamStatuses?: Record<string, number>;
  barrierReleaseReason?: "target" | "timeout";
};

type StressSummary = {
  ok: boolean;
  agents: number;
  finalOk: number;
  failures: number;
  firstFailure?: string;
  modelRequests: number;
  modelPeakActive: number;
  modelStatuses?: Record<string, number>;
  upstreamRequests?: number;
  upstreamPeakActive?: number;
  upstreamStatuses?: Record<string, number>;
  barrierReleaseReason?: "target" | "timeout";
  responseDelayMs: number;
  upstreamBaseUrl?: string;
  modelId: string;
  paths: Record<string, number>;
};

function parsePositiveIntEnv(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

function parseBooleanEnv(name: string, fallback = false): boolean {
  const raw = process.env[name]?.trim().toLowerCase();
  if (!raw) {
    return fallback;
  }
  if (["1", "true", "yes", "on"].includes(raw)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(raw)) {
    return false;
  }
  throw new Error(`${name} must be a boolean`);
}

function parseOptionalPositiveIntEnv(name: string): number | undefined {
  const raw = process.env[name]?.trim();
  if (!raw) {
    return undefined;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

function parseStringListEnv(name: string): string[] {
  const raw = process.env[name]?.trim();
  if (!raw) {
    return [];
  }
  return raw
    .split(/[\s,;]+/g)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
}

async function getFreePort(): Promise<number> {
  const server = await import("node:net").then(({ createServer }) => createServer());
  return await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => {
        if (!address || typeof address === "string") {
          reject(new Error("failed to allocate port"));
          return;
        }
        resolve(address.port);
      });
    });
  });
}

function writeJson(res: import("node:http").ServerResponse, status: number, value: unknown): void {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(value));
}

function writeSse(res: import("node:http").ServerResponse, events: unknown[]): void {
  const text = `${events
    .map((event) => `data: ${JSON.stringify(event)}\n\n`)
    .join("")}data: [DONE]\n\n`;
  res.writeHead(200, { "content-type": "text/event-stream" });
  res.end(text);
}

async function startOpenAiResponsesConcurrencyMock(params: {
  responseDelayMs: number;
  modelId: string;
  rateLimitBearerTokens?: string[];
}): Promise<{ baseUrl: string; stats: FetchStats; close: () => Promise<void> }> {
  const stats: FetchStats = {
    totalRequests: 0,
    activeRequests: 0,
    peakActive: 0,
    paths: {},
    statuses: {},
  };
  const rateLimitBearerTokens = new Set(params.rateLimitBearerTokens ?? []);
  const server = createServer((req, res) => {
    void (async () => {
      const url = new URL(req.url ?? "/", "http://127.0.0.1");
      if (req.method === "GET" && url.pathname === "/v1/models") {
        writeJson(res, 200, {
          object: "list",
          data: [{ id: params.modelId, object: "model", owned_by: "openclaw-stress" }],
        });
        return;
      }
      if (req.method !== "POST" || url.pathname !== "/v1/responses") {
        writeJson(res, 404, {
          error: { message: `unexpected mock route: ${req.method} ${url.pathname}` },
        });
        return;
      }

      stats.totalRequests += 1;
      stats.activeRequests += 1;
      stats.peakActive = Math.max(stats.peakActive, stats.activeRequests);
      stats.paths[url.pathname] = (stats.paths[url.pathname] ?? 0) + 1;
      try {
        for await (const _chunk of req) {
          // Drain request body so the client can finish sending before we delay.
        }
        const authorization =
          typeof req.headers.authorization === "string" ? req.headers.authorization : "";
        const bearer = authorization.match(/^Bearer\s+(.+)$/i)?.[1]?.trim();
        if (bearer && rateLimitBearerTokens.has(bearer)) {
          stats.statuses = stats.statuses ?? {};
          stats.statuses["429"] = (stats.statuses["429"] ?? 0) + 1;
          writeJson(res, 429, {
            error: {
              type: "rate_limit_error",
              code: "rate_limit",
              message: "mock API key rate limit",
            },
          });
          return;
        }
        if (params.responseDelayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, params.responseDelayMs));
        }
        stats.statuses = stats.statuses ?? {};
        stats.statuses["200"] = (stats.statuses["200"] ?? 0) + 1;
        writeSse(res, [
        {
          type: "response.output_item.added",
          item: {
            type: "message",
            id: "msg_stress_1",
            role: "assistant",
            content: [],
            status: "in_progress",
          },
        },
        { type: "response.output_text.delta", delta: "ok" },
        {
          type: "response.output_item.done",
          item: {
            type: "message",
            id: "msg_stress_1",
            role: "assistant",
            status: "completed",
            content: [{ type: "output_text", text: "ok", annotations: [] }],
          },
        },
        {
          type: "response.completed",
          response: {
            status: "completed",
            usage: {
              input_tokens: 1,
              output_tokens: 1,
              total_tokens: 2,
              input_tokens_details: { cached_tokens: 0 },
            },
          },
        },
        ]);
      } finally {
        stats.activeRequests -= 1;
      }
    })().catch((error: unknown) => {
      stats.activeRequests = Math.max(0, stats.activeRequests - 1);
      writeJson(res, 500, {
        error: { message: error instanceof Error ? error.message : String(error) },
      });
    });
  });

  const port = await new Promise<number>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("mock server did not bind to a TCP port"));
        return;
      }
      resolve(address.port);
    });
  });

  return {
    baseUrl: `http://127.0.0.1:${port}/v1`,
    stats,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  };
}

async function startOpenAiResponsesConcurrencyProxy(params: {
  upstreamBaseUrl: string;
  upstreamApiKey: string;
  modelId: string;
  targetConcurrent: number;
  barrierTimeoutMs: number;
  requestTimeoutMs: number;
  forceMaxOutputTokens?: number;
}): Promise<{ baseUrl: string; stats: FetchStats; close: () => Promise<void> }> {
  const stats: FetchStats = {
    totalRequests: 0,
    activeRequests: 0,
    peakActive: 0,
    paths: {},
    upstreamRequests: 0,
    upstreamActiveRequests: 0,
    upstreamPeakActive: 0,
    upstreamStatuses: {},
  };
  const pendingReleases = new Set<() => void>();
  let barrierTimer: ReturnType<typeof setTimeout> | undefined;
  let barrierReleased = false;
  const releaseBarrier = (reason: "target" | "timeout") => {
    if (barrierReleased) {
      return;
    }
    barrierReleased = true;
    stats.barrierReleaseReason = reason;
    if (barrierTimer) {
      clearTimeout(barrierTimer);
      barrierTimer = undefined;
    }
    for (const release of Array.from(pendingReleases)) {
      release();
    }
    pendingReleases.clear();
  };
  const waitForBarrier = () => {
    if (barrierReleased) {
      return Promise.resolve();
    }
    if (!barrierTimer) {
      barrierTimer = setTimeout(() => releaseBarrier("timeout"), params.barrierTimeoutMs);
      barrierTimer.unref?.();
    }
    return new Promise<void>((resolve) => {
      pendingReleases.add(resolve);
      if (stats.peakActive >= params.targetConcurrent) {
        releaseBarrier("target");
      }
    });
  };
  const upstreamBase = params.upstreamBaseUrl.replace(/\/+$/, "");
  const server = createServer((req, res) => {
    void (async () => {
      const url = new URL(req.url ?? "/", "http://127.0.0.1");
      if (req.method === "GET" && url.pathname === "/v1/models") {
        writeJson(res, 200, {
          object: "list",
          data: [{ id: params.modelId, object: "model", owned_by: "openclaw-live-stress" }],
        });
        return;
      }
      if (req.method !== "POST" || url.pathname !== "/v1/responses") {
        writeJson(res, 404, { error: { message: `unexpected proxy route: ${req.method} ${url.pathname}` } });
        return;
      }

      stats.totalRequests += 1;
      stats.activeRequests += 1;
      stats.peakActive = Math.max(stats.peakActive, stats.activeRequests);
      stats.paths[url.pathname] = (stats.paths[url.pathname] ?? 0) + 1;
      try {
        const chunks: Buffer[] = [];
        for await (const chunk of req) {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        }
        await waitForBarrier();
        let body = Buffer.concat(chunks).toString("utf8");
        try {
          const parsed = JSON.parse(body) as Record<string, unknown>;
          parsed.model = params.modelId;
          parsed.stream = true;
          if (params.forceMaxOutputTokens !== undefined) {
            parsed.max_output_tokens = params.forceMaxOutputTokens;
          }
          body = JSON.stringify(parsed);
        } catch {
          // Preserve the original body if the upstream-compatible request is not JSON.
        }

        stats.upstreamRequests = (stats.upstreamRequests ?? 0) + 1;
        stats.upstreamActiveRequests = (stats.upstreamActiveRequests ?? 0) + 1;
        stats.upstreamPeakActive = Math.max(
          stats.upstreamPeakActive ?? 0,
          stats.upstreamActiveRequests ?? 0,
        );
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), params.requestTimeoutMs);
        try {
          const upstream = await fetch(`${upstreamBase}/responses`, {
            method: "POST",
            headers: {
              Authorization: `Bearer ${params.upstreamApiKey}`,
              "Content-Type": "application/json",
            },
            body,
            signal: controller.signal,
          });
          const statusKey = String(upstream.status);
          stats.upstreamStatuses = stats.upstreamStatuses ?? {};
          stats.upstreamStatuses[statusKey] = (stats.upstreamStatuses[statusKey] ?? 0) + 1;
          const headers: Record<string, string> = {};
          const contentType = upstream.headers.get("content-type") ?? "text/event-stream";
          headers["content-type"] = contentType;
          res.writeHead(upstream.status, headers);
          if (upstream.body) {
            await new Promise<void>((resolve, reject) => {
              Readable.fromWeb(upstream.body as never)
                .on("error", reject)
                .on("end", resolve)
                .pipe(res, { end: true });
            });
          } else {
            res.end();
          }
        } finally {
          clearTimeout(timeout);
          stats.upstreamActiveRequests = Math.max(0, (stats.upstreamActiveRequests ?? 0) - 1);
        }
      } finally {
        stats.activeRequests -= 1;
      }
    })().catch((error: unknown) => {
      stats.activeRequests = Math.max(0, stats.activeRequests - 1);
      stats.upstreamActiveRequests = Math.max(0, (stats.upstreamActiveRequests ?? 0) - 1);
      writeJson(res, 500, {
        error: { message: error instanceof Error ? error.message : String(error) },
      });
    });
  });

  const port = await new Promise<number>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("proxy server did not bind to a TCP port"));
        return;
      }
      resolve(address.port);
    });
  });

  return {
    baseUrl: `http://127.0.0.1:${port}/v1`,
    stats,
    close: () =>
      new Promise<void>((resolve, reject) => {
        releaseBarrier("timeout");
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  };
}

async function resetGatewayRuntimeState() {
  clearRuntimeConfigSnapshot();
  clearConfigCache();
  clearSessionStoreCacheForTest();
  resetAgentRunContextForTest();
  clearAllBootstrapSnapshots();
  clearGatewaySubagentRuntime();
}

async function main() {
  const total = parsePositiveIntEnv("OPENCLAW_STRESS_AGENTS", 1000);
  const responseDelayMs = parsePositiveIntEnv("OPENCLAW_STRESS_RESPONSE_DELAY_MS", 30_000);
  const requestTimeoutMs = parsePositiveIntEnv("OPENCLAW_STRESS_REQUEST_TIMEOUT_MS", 240_000);
  const upstreamBaseUrl = process.env.OPENCLAW_STRESS_UPSTREAM_BASE_URL?.trim();
  const upstreamApiKeyEnv = process.env.OPENCLAW_STRESS_UPSTREAM_API_KEY_ENV?.trim() || "CRS_API_KEY";
  const upstreamApiKey = upstreamBaseUrl ? process.env[upstreamApiKeyEnv]?.trim() : undefined;
  const barrierTimeoutMs = parsePositiveIntEnv(
    "OPENCLAW_STRESS_UPSTREAM_BARRIER_TIMEOUT_MS",
    180_000,
  );
  const forceMaxOutputTokens = parseOptionalPositiveIntEnv(
    "OPENCLAW_STRESS_UPSTREAM_MAX_OUTPUT_TOKENS",
  );
  const rateLimitBearerTokens = parseStringListEnv("OPENCLAW_STRESS_RATE_LIMIT_BEARER_TOKENS");
  const allowFailures = parseBooleanEnv("OPENCLAW_STRESS_ALLOW_FAILURES", false);
  if (total > DEFAULT_SUBAGENT_MAX_CONCURRENT) {
    throw new Error(
      `requested ${total} agents but default subagent concurrency is ${DEFAULT_SUBAGENT_MAX_CONCURRENT}`,
    );
  }
  if (upstreamBaseUrl && !upstreamApiKey) {
    throw new Error(
      `OPENCLAW_STRESS_UPSTREAM_BASE_URL is set, but ${upstreamApiKeyEnv} is not available`,
    );
  }

  const previousEnv = {
    HOME: process.env.HOME,
    OPENCLAW_STATE_DIR: process.env.OPENCLAW_STATE_DIR,
    OPENCLAW_CONFIG_PATH: process.env.OPENCLAW_CONFIG_PATH,
    OPENCLAW_GATEWAY_TOKEN: process.env.OPENCLAW_GATEWAY_TOKEN,
    OPENCLAW_SKIP_CHANNELS: process.env.OPENCLAW_SKIP_CHANNELS,
    OPENCLAW_SKIP_GMAIL_WATCHER: process.env.OPENCLAW_SKIP_GMAIL_WATCHER,
    OPENCLAW_SKIP_CRON: process.env.OPENCLAW_SKIP_CRON,
    OPENCLAW_SKIP_CANVAS_HOST: process.env.OPENCLAW_SKIP_CANVAS_HOST,
    OPENCLAW_SKIP_BROWSER_CONTROL_SERVER: process.env.OPENCLAW_SKIP_BROWSER_CONTROL_SERVER,
    OPENCLAW_SKIP_PROVIDERS: process.env.OPENCLAW_SKIP_PROVIDERS,
    OPENCLAW_BUNDLED_PLUGINS_DIR: process.env.OPENCLAW_BUNDLED_PLUGINS_DIR,
    OPENCLAW_DISABLE_BUNDLED_PLUGINS: process.env.OPENCLAW_DISABLE_BUNDLED_PLUGINS,
    OPENCLAW_TEST_MINIMAL_GATEWAY: process.env.OPENCLAW_TEST_MINIMAL_GATEWAY,
  };
  const tempHome = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-gateway-stress-"));
  const stateDir = path.join(tempHome, ".openclaw");
  const workspaceDir = path.join(tempHome, "workspace");
  const bundledPluginsDir = path.join(tempHome, "empty-bundled-plugins");
  const configPath = path.join(stateDir, "openclaw.json");
  const token = `stress-${randomUUID()}`;
  const providerId = "stress-openai";
  const modelId =
    process.env.OPENCLAW_STRESS_MODEL?.trim() ||
    (upstreamBaseUrl ? "gpt-5.4-mini" : "stress-mini");
  let client: GatewayClient | undefined;
  let server: Awaited<ReturnType<typeof startGatewayServer>> | undefined;
  const modelServer = upstreamBaseUrl
    ? await startOpenAiResponsesConcurrencyProxy({
        upstreamBaseUrl,
        upstreamApiKey: upstreamApiKey as string,
        modelId,
        targetConcurrent: total,
        barrierTimeoutMs,
        requestTimeoutMs,
        forceMaxOutputTokens: forceMaxOutputTokens ?? 4,
      })
    : await startOpenAiResponsesConcurrencyMock({ responseDelayMs, modelId, rateLimitBearerTokens });
  const baseUrl = modelServer.baseUrl;

  try {
    await fs.mkdir(path.dirname(configPath), { recursive: true });
    await fs.mkdir(workspaceDir, { recursive: true });
    await fs.mkdir(bundledPluginsDir, { recursive: true });

    process.env.HOME = tempHome;
    process.env.OPENCLAW_STATE_DIR = stateDir;
    process.env.OPENCLAW_CONFIG_PATH = configPath;
    process.env.OPENCLAW_GATEWAY_TOKEN = token;
    process.env.OPENCLAW_SKIP_CHANNELS = "1";
    process.env.OPENCLAW_SKIP_GMAIL_WATCHER = "1";
    process.env.OPENCLAW_SKIP_CRON = "1";
    process.env.OPENCLAW_SKIP_CANVAS_HOST = "1";
    process.env.OPENCLAW_SKIP_BROWSER_CONTROL_SERVER = "1";
    process.env.OPENCLAW_SKIP_PROVIDERS = "1";
    process.env.OPENCLAW_BUNDLED_PLUGINS_DIR = bundledPluginsDir;
    process.env.OPENCLAW_DISABLE_BUNDLED_PLUGINS = "1";
    process.env.OPENCLAW_TEST_MINIMAL_GATEWAY = "1";

    const cfg = {
      agents: {
        defaults: {
          workspace: workspaceDir,
          model: { primary: `${providerId}/${modelId}` },
          skipBootstrap: true,
          maxConcurrent: total,
          subagents: {
            maxConcurrent: total,
            maxChildrenPerAgent: total,
          },
          models: {
            [`${providerId}/${modelId}`]: {
              params: {
                transport: "sse",
                openaiWsWarmup: false,
                maxTokens: 8,
              },
            },
          },
        },
      },
      models: {
        mode: "replace",
        providers: {
          [providerId]: {
            baseUrl,
            apiKey: "stress-test",
            api: "openai-responses",
            models: [
              {
                id: modelId,
                name: modelId,
                api: "openai-responses",
                reasoning: false,
                input: ["text"],
                cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
                contextWindow: 1_000_000,
                maxTokens: 16,
              },
            ],
          },
        },
      },
      plugins: { enabled: false },
      gateway: { auth: { mode: "token", token } },
    };
    await fs.writeFile(configPath, `${JSON.stringify(cfg, null, 2)}\n`);
    await resetGatewayRuntimeState();

    const port = await getFreePort();
    server = await startGatewayServer(port, {
      bind: "loopback",
      auth: { mode: "token", token },
      controlUiEnabled: false,
      deferStartupSidecars: true,
    });
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("gateway connect timeout")), 10_000);
      const connected = new GatewayClient({
        url: `ws://127.0.0.1:${port}`,
        token,
        clientDisplayName: "gateway-agent-concurrency-stress",
        requestTimeoutMs,
        scopes: ["operator.admin"],
        onHelloOk: () => {
          clearTimeout(timeout);
          resolve();
        },
        onConnectError: (error) => {
          clearTimeout(timeout);
          reject(error);
        },
      });
      client = connected;
      connected.start();
    });

    const requests = Array.from({ length: total }, async (_, index) => {
      const payload = await (client as GatewayClient).request<AgentResult>(
        "agent",
        {
          sessionKey: `agent:main:stress:${index}`,
          idempotencyKey: `stress-${index}-${randomUUID()}`,
          message: `Reply exactly ok for stress run ${index}.`,
          deliver: false,
          disableMessageTool: true,
          lane: "subagent",
          timeout: Math.ceil(requestTimeoutMs / 1000),
          promptMode: "none",
          modelRun: true,
          suppressPromptPersistence: true,
          sessionEffects: "internal",
        },
        { expectFinal: true, timeoutMs: requestTimeoutMs },
      );
      if (payload.status !== "ok") {
        throw new Error(`agent ${index} final status ${payload.status}: ${JSON.stringify(payload)}`);
      }
      return payload;
    });

    const settled = await Promise.allSettled(requests);
    const results = settled.filter(
      (result): result is PromiseFulfilledResult<AgentResult> => result.status === "fulfilled",
    );
    const failures = settled.filter(
      (result): result is PromiseRejectedResult => result.status === "rejected",
    );
    const firstFailure = failures[0]?.reason instanceof Error
      ? failures[0].reason.message
      : failures[0]
        ? String(failures[0].reason)
        : undefined;
    const summary: StressSummary = {
      ok: results.length === total,
      agents: total,
      finalOk: results.length,
      failures: failures.length,
      ...(firstFailure ? { firstFailure } : {}),
      modelRequests: modelServer.stats.totalRequests,
      modelPeakActive: modelServer.stats.peakActive,
      modelStatuses: modelServer.stats.statuses,
      upstreamRequests: modelServer.stats.upstreamRequests,
      upstreamPeakActive: modelServer.stats.upstreamPeakActive,
      upstreamStatuses: modelServer.stats.upstreamStatuses,
      barrierReleaseReason: modelServer.stats.barrierReleaseReason,
      responseDelayMs,
      upstreamBaseUrl: upstreamBaseUrl ? new URL(upstreamBaseUrl).origin : undefined,
      modelId,
      paths: modelServer.stats.paths,
    };
    console.log(JSON.stringify(summary));

    if (results.length !== total && !allowFailures) {
      throw new Error(`expected ${total} final results, got ${results.length}`);
    }
    if (modelServer.stats.totalRequests < total && !allowFailures) {
      throw new Error(
        `expected at least ${total} model requests, got ${modelServer.stats.totalRequests}`,
      );
    }
    if (rateLimitBearerTokens.length > 0 && !allowFailures) {
      const status200 = modelServer.stats.statuses?.["200"] ?? 0;
      const status429 = modelServer.stats.statuses?.["429"] ?? 0;
      if (status200 < total || status429 < 1) {
        throw new Error(
          `expected key-pool run to finish ${total} successes after mocked rate limits, ` +
            `got 200=${status200} 429=${status429}`,
        );
      }
    }
    if (
      rateLimitBearerTokens.length === 0 &&
      modelServer.stats.peakActive < total &&
      !allowFailures
    ) {
      throw new Error(`expected model peakActive >= ${total}, got ${modelServer.stats.peakActive}`);
    }
    if (upstreamBaseUrl && (modelServer.stats.upstreamPeakActive ?? 0) < total && !allowFailures) {
      throw new Error(
        `expected upstream peakActive >= ${total}, got ${modelServer.stats.upstreamPeakActive ?? 0}`,
      );
    }
    if (!summary.ok && !allowFailures) {
      throw new Error(`stress run failed: ${firstFailure ?? "unknown failure"}`);
    }
    if (!summary.ok && allowFailures) {
      process.exitCode = 1;
    }
  } finally {
    await client?.stopAndWait({ timeoutMs: 2_000 }).catch(() => client?.stop());
    await server?.close({ reason: "gateway agent concurrency stress complete" }).catch(() => {});
    await modelServer.close().catch(() => {});
    await fs.rm(tempHome, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
    await resetGatewayRuntimeState();
  }
}

await main();
