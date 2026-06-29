import fs from "node:fs/promises";
import path from "node:path";
import { detectMime, normalizeMimeType } from "@openclaw/media-core/mime";
import type { RuntimeRunSpec } from "../../packages/gateway-protocol/src/schema/enterprise-runtime.js";
import type { ImageContent } from "../agents/command/types.js";
import { EnterpriseRuntimeError } from "./errors.js";

const DEFAULT_MAX_IMAGE_ATTACHMENTS = 10;
const DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ALLOWED_IMAGE_MIMES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

export type ResolvedRuntimeAttachment = {
  name: string;
  path: string;
  realPath: string;
  kind?: string;
  mimeType?: string;
  sizeBytes: number;
  image?: ImageContent;
};

function assertInsideWorkspace(params: {
  name: string;
  realPath: string;
  workspaceRoot: string;
}): void {
  const relative = path.relative(params.workspaceRoot, params.realPath);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_WORKSPACE_FORBIDDEN",
      "attachment must be inside workspace",
      { attachment: params.name, path: params.realPath, workspaceRoot: params.workspaceRoot },
    );
  }
}

function declaredMimeFromAttachment(kind: string | undefined): string | undefined {
  const normalized = normalizeMimeType(kind);
  if (!normalized) {
    return undefined;
  }
  if (normalized === "image") {
    return undefined;
  }
  return normalized;
}

function shouldResolveAsImage(params: { kind?: string; mimeType?: string }): boolean {
  const kind = params.kind?.trim().toLowerCase();
  return (
    kind === "image" ||
    kind?.startsWith("image/") === true ||
    params.mimeType?.startsWith("image/") === true
  );
}

async function readFileHead(filePath: string, sizeBytes: number): Promise<Buffer> {
  const handle = await fs.open(filePath, "r");
  try {
    const buffer = Buffer.alloc(Math.min(sizeBytes, 4096));
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    return buffer.subarray(0, bytesRead);
  } finally {
    await handle.close();
  }
}

function imageMimeFromMagic(head: Buffer): string | undefined {
  if (
    head.length >= 8 &&
    head[0] === 0x89 &&
    head[1] === 0x50 &&
    head[2] === 0x4e &&
    head[3] === 0x47 &&
    head[4] === 0x0d &&
    head[5] === 0x0a &&
    head[6] === 0x1a &&
    head[7] === 0x0a
  ) {
    return "image/png";
  }
  if (head.length >= 3 && head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    head.length >= 12 &&
    head.subarray(0, 4).toString("ascii") === "RIFF" &&
    head.subarray(8, 12).toString("ascii") === "WEBP"
  ) {
    return "image/webp";
  }
  if (
    head.length >= 6 &&
    (head.subarray(0, 6).toString("ascii") === "GIF87a" ||
      head.subarray(0, 6).toString("ascii") === "GIF89a")
  ) {
    return "image/gif";
  }
  return undefined;
}

async function resolveImageAttachment(params: {
  name: string;
  realPath: string;
  kind?: string;
  sizeBytes: number;
}): Promise<ImageContent | undefined> {
  const declaredMime = declaredMimeFromAttachment(params.kind);
  const head = await readFileHead(params.realPath, params.sizeBytes);
  const magicMime = imageMimeFromMagic(head);
  const mimeType = normalizeMimeType(await detectMime({ buffer: head, filePath: params.realPath }));
  if (!shouldResolveAsImage({ kind: params.kind, mimeType: magicMime ?? mimeType })) {
    return undefined;
  }
  if (params.sizeBytes <= 0) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_INVALID_SPEC",
      `empty image attachment: ${params.name}`,
    );
  }
  if (!magicMime) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_INVALID_SPEC",
      `attachment '${params.name}' is not a supported image`,
    );
  }
  const effectiveMimeType = magicMime;
  if (declaredMime?.startsWith("image/") && declaredMime !== effectiveMimeType) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_INVALID_SPEC",
      `image attachment MIME mismatch: declared ${declaredMime}, detected ${effectiveMimeType}`,
    );
  }
  if (!ALLOWED_IMAGE_MIMES.has(effectiveMimeType)) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_INVALID_SPEC",
      `unsupported image attachment MIME type: ${effectiveMimeType}`,
    );
  }
  if (params.sizeBytes > DEFAULT_MAX_IMAGE_BYTES) {
    throw new EnterpriseRuntimeError(
      "RUNTIME_INVALID_SPEC",
      `image attachment too large: ${params.sizeBytes} bytes`,
      { attachment: params.name, maxBytes: DEFAULT_MAX_IMAGE_BYTES },
    );
  }
  const buffer = await fs.readFile(params.realPath);
  return {
    type: "image",
    data: buffer.toString("base64"),
    mimeType: effectiveMimeType,
  };
}

export async function resolveRuntimeAttachments(params: {
  spec: RuntimeRunSpec;
  workspaceRoot: string;
}): Promise<ResolvedRuntimeAttachment[]> {
  const attachments = params.spec.input.attachments ?? [];
  if (!attachments.length) {
    return [];
  }
  let imageCount = 0;
  const resolved: ResolvedRuntimeAttachment[] = [];
  for (const attachment of attachments) {
    let realPath: string;
    try {
      realPath = await fs.realpath(attachment.path);
    } catch {
      throw new EnterpriseRuntimeError(
        "RUNTIME_WORKSPACE_FORBIDDEN",
        `attachment not found: ${attachment.path}`,
      );
    }
    assertInsideWorkspace({
      name: attachment.name,
      realPath,
      workspaceRoot: params.workspaceRoot,
    });
    const stat = await fs.stat(realPath);
    if (!stat.isFile()) {
      throw new EnterpriseRuntimeError(
        "RUNTIME_INVALID_SPEC",
        `attachment must be a file: ${attachment.path}`,
      );
    }
    const image = await resolveImageAttachment({
      name: attachment.name,
      realPath,
      kind: attachment.kind,
      sizeBytes: stat.size,
    });
    if (image) {
      imageCount += 1;
      if (imageCount > DEFAULT_MAX_IMAGE_ATTACHMENTS) {
        throw new EnterpriseRuntimeError(
          "RUNTIME_INVALID_SPEC",
          `too many image attachments: ${imageCount}`,
          { maxImages: DEFAULT_MAX_IMAGE_ATTACHMENTS },
        );
      }
    }
    resolved.push({
      name: attachment.name,
      path: attachment.path,
      realPath,
      ...(attachment.kind ? { kind: attachment.kind } : {}),
      sizeBytes: stat.size,
      ...(image ? { mimeType: image.mimeType, image } : {}),
    });
  }
  return resolved;
}
