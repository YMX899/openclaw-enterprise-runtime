#!/usr/bin/env node
import crypto from "node:crypto";

const url = process.env.OPENCLAW_GATEWAY_URL || "";
const token = process.env.OPENCLAW_GATEWAY_TOKEN || "";
const doChatSend = process.argv.includes("--chat-send") || process.env.OPENCLAW_GATEWAY_WS_CHAT_SEND === "1";

if (!url || !token) {
  console.error("OPENCLAW_GATEWAY_URL and OPENCLAW_GATEWAY_TOKEN are required; token value is never printed.");
  process.exit(2);
}

const PROTOCOL_VERSION = 3;
const CLIENT_ID = "gateway-client";
const CLIENT_MODE = "backend";
const PLATFORM = "node";
const DEVICE_FAMILY = "Bridge";
const READ_WRITE_SCOPES = ["operator.read", "operator.write"];
const SESSION_KEY = "agent:main:bridge-contract-ws-script";
const RUN_ID = `bridge-contract-ws-script-${Date.now()}`;
const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function base64url(data) {
  return Buffer.from(data).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/g, "");
}

function rawPublicKeyFromPem(publicKeyPem) {
  const spki = crypto.createPublicKey(publicKeyPem).export({ type: "spki", format: "der" });
  if (spki.length === ED25519_SPKI_PREFIX.length + 32 && spki.subarray(0, ED25519_SPKI_PREFIX.length).equals(ED25519_SPKI_PREFIX)) {
    return spki.subarray(ED25519_SPKI_PREFIX.length);
  }
  return spki;
}

function normalizeMetadata(value) {
  return String(value || "").trim().replace(/[A-Z]/g, (char) => String.fromCharCode(char.charCodeAt(0) + 32));
}

function buildDeviceAuthPayloadV3(params) {
  return [
    "v3",
    params.deviceId,
    params.clientId,
    params.clientMode,
    params.role,
    params.scopes.join(","),
    String(params.signedAtMs),
    params.token || "",
    params.nonce,
    normalizeMetadata(params.platform),
    normalizeMetadata(params.deviceFamily),
  ].join("|");
}

function sign(privateKeyPem, payload) {
  return base64url(crypto.sign(null, Buffer.from(payload, "utf8"), crypto.createPrivateKey(privateKeyPem)));
}

function createEphemeralDeviceIdentity() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const publicKeyPem = publicKey.export({ type: "spki", format: "pem" }).toString();
  const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
  const publicRaw = rawPublicKeyFromPem(publicKeyPem);
  return {
    deviceId: crypto.createHash("sha256").update(publicRaw).digest("hex"),
    publicKey: base64url(publicRaw),
    privateKeyPem,
  };
}

function scrub(value) {
  if (Array.isArray(value)) return value.map(scrub);
  if (value && typeof value === "object") {
    const out = {};
    for (const [key, nested] of Object.entries(value)) {
      if (/token|password|secret|authorization|signature|publicKey|privateKey|deviceId|instanceId/i.test(key)) {
        out[key] = "<redacted>";
      } else {
        out[key] = scrub(nested);
      }
    }
    return out;
  }
  if (typeof value === "string" && value.includes(token)) return value.replaceAll(token, "<redacted>");
  return value;
}

class GatewayClient {
  constructor(authToken, { includeDevice = false, scopes = READ_WRITE_SCOPES } = {}) {
    this.authToken = authToken;
    this.includeDevice = includeDevice;
    this.scopes = scopes;
    this.pending = new Map();
    this.events = [];
    this.seq = 1;
    this.device = includeDevice ? createEphemeralDeviceIdentity() : null;
  }

  async open() {
    this.ws = new WebSocket(url);
    this.ws.addEventListener("message", (event) => {
      let frame;
      try {
        frame = JSON.parse(event.data);
      } catch {
        return;
      }
      if (frame.type === "res" && frame.id && this.pending.has(frame.id)) {
        const resolve = this.pending.get(frame.id);
        this.pending.delete(frame.id);
        resolve(frame);
      } else if (frame.type === "event") {
        this.events.push(frame);
      }
    });
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("WebSocket open timeout")), 5000);
      this.ws.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.ws.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("WebSocket open error"));
      }, { once: true });
    });
    return await this.waitForChallenge();
  }

  async waitForChallenge() {
    const started = Date.now();
    while (Date.now() - started < 5000) {
      const challenge = this.events.find((frame) => frame.event === "connect.challenge");
      if (challenge && challenge.payload) return challenge.payload;
      await sleep(50);
    }
    throw new Error("connect.challenge timeout");
  }

  request(method, params = {}, timeoutMs = 10000) {
    const id = `ws-contract-${this.seq++}`;
    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timeout`));
      }, timeoutMs);
      this.pending.set(id, (frame) => {
        clearTimeout(timer);
        resolve(frame);
      });
    });
    this.ws.send(JSON.stringify({ type: "req", id, method, params }));
    return promise;
  }

  async connect(challenge) {
    const params = {
      minProtocol: PROTOCOL_VERSION,
      maxProtocol: PROTOCOL_VERSION,
      client: {
        id: CLIENT_ID,
        version: "openclaw-video-ws-contract",
        platform: PLATFORM,
        mode: CLIENT_MODE,
        deviceFamily: DEVICE_FAMILY,
        instanceId: crypto.randomUUID(),
      },
      role: "operator",
      scopes: this.scopes,
      caps: [],
      commands: [],
      permissions: {},
      auth: { token: this.authToken },
      locale: "zh-CN",
      userAgent: "openclaw-video-gateway-ws-contract/0.1",
    };
    if (this.device) {
      const signedAt = Date.now();
      const nonce = challenge.nonce;
      const payload = buildDeviceAuthPayloadV3({
        deviceId: this.device.deviceId,
        clientId: CLIENT_ID,
        clientMode: CLIENT_MODE,
        role: "operator",
        scopes: this.scopes,
        signedAtMs: signedAt,
        token: this.authToken,
        nonce,
        platform: PLATFORM,
        deviceFamily: DEVICE_FAMILY,
      });
      params.device = {
        id: this.device.deviceId,
        publicKey: this.device.publicKey,
        signature: sign(this.device.privateKeyPem, payload),
        signedAt,
        nonce,
      };
    }
    return await this.request("connect", params);
  }

  async waitForChatTerminal(runId, timeoutMs = 15000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const terminal = this.events.find((frame) => {
        const payload = frame.payload || {};
        return frame.event === "chat" && payload.runId === runId && ["final", "error", "aborted"].includes(payload.state);
      });
      if (terminal) return terminal;
      await sleep(250);
    }
    return null;
  }

  close() {
    try {
      this.ws?.close();
    } catch {
      // best effort
    }
  }
}

function assertFrame(condition, label, details) {
  if (!condition) {
    const error = new Error(`${label} failed`);
    error.details = details;
    throw error;
  }
}

async function runWithClient(client, fn) {
  try {
    const challenge = await client.open();
    const connected = await client.connect(challenge);
    return await fn(client, connected);
  } finally {
    client.close();
  }
}

const output = {
  timestamp: new Date().toISOString(),
  url,
  chatSendEnabled: doChatSend,
  checks: {},
};

try {
  output.checks.wrongToken = await runWithClient(
    new GatewayClient("__wrong_openclaw_contract_token__", { includeDevice: false }),
    async (_client, connected) => {
      assertFrame(connected.ok === false, "wrong token rejection", connected);
      const code = connected.error?.details?.code || connected.error?.message || "";
      assertFrame(String(code).includes("AUTH_TOKEN_MISMATCH") || String(connected.error?.message || "").includes("token mismatch"), "wrong token error code", connected);
      return scrub({ ok: true, response: connected });
    },
  );

  output.checks.unsignedScopesFailClosed = await runWithClient(
    new GatewayClient(token, { includeDevice: false, scopes: READ_WRITE_SCOPES }),
    async (client, connected) => {
      assertFrame(connected.ok === true, "unsigned connect", connected);
      const history = await client.request("chat.history", { sessionKey: SESSION_KEY, limit: 1 });
      assertFrame(history.ok === false && String(history.error?.message || "").includes("missing scope"), "unsigned chat.history scope gate", history);
      return scrub({ ok: true, connectOk: connected.ok, history });
    },
  );

  output.checks.signedReadWrite = await runWithClient(
    new GatewayClient(token, { includeDevice: true, scopes: READ_WRITE_SCOPES }),
    async (client, connected) => {
      assertFrame(connected.ok === true, "signed connect", connected);
      const status = await client.request("status", {});
      assertFrame(status.ok === true, "signed status", status);
      const history = await client.request("chat.history", { sessionKey: SESSION_KEY, limit: 1 });
      assertFrame(history.ok === true, "signed chat.history", history);
      const result = { ok: true, connect: connected, status, history };
      if (doChatSend) {
        const send = await client.request("chat.send", {
          sessionKey: SESSION_KEY,
          message: "Return OK only.",
          idempotencyKey: RUN_ID,
          deliver: false,
          timeoutMs: 5000,
        });
        assertFrame(send.ok === true && send.payload?.status === "started", "signed chat.send ack", send);
        const terminal = await client.waitForChatTerminal(RUN_ID);
        assertFrame(Boolean(terminal), "signed chat.send terminal event", send);
        result.send = send;
        result.terminal = terminal;
      }
      return scrub(result);
    },
  );

  console.log(JSON.stringify(output, null, 2));
} catch (err) {
  const failure = {
    error: err.message,
    details: scrub(err.details),
    partial: scrub(output),
  };
  console.error(JSON.stringify(failure, null, 2));
  process.exit(1);
}
