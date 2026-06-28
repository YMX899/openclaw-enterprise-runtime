export type ModelKeyLeaseErrorClass =
  | "rate_limit"
  | "quota_exhausted"
  | "auth_error"
  | "overloaded"
  | "network"
  | "server_error";

export function classifyModelKeyLeaseError(error: unknown): ModelKeyLeaseErrorClass | undefined {
  const message = error instanceof Error ? error.message : String(error ?? "");
  const normalized = message.toLowerCase();
  if (normalized.includes("rate limit") || normalized.includes("429")) {
    return "rate_limit";
  }
  if (normalized.includes("quota") || normalized.includes("insufficient_quota")) {
    return "quota_exhausted";
  }
  if (
    normalized.includes("invalid api key") ||
    normalized.includes("unauthorized") ||
    normalized.includes("401") ||
    normalized.includes("403")
  ) {
    return "auth_error";
  }
  if (normalized.includes("overload") || normalized.includes("503")) {
    return "overloaded";
  }
  if (
    normalized.includes("timeout") ||
    normalized.includes("econn") ||
    normalized.includes("network")
  ) {
    return "network";
  }
  if (normalized.includes("500") || normalized.includes("502") || normalized.includes("504")) {
    return "server_error";
  }
  return undefined;
}
