import type { ProviderCredentialPool } from "../config/types.js";

export type ModelKeyLease = {
  authPoolId: string;
  keyId: string;
  secret: string;
  release(errorClass?: string): void;
};

export type ModelKeyBrokerAcquireParams = {
  pools?: ProviderCredentialPool[];
  authPoolId: string;
  provider: string;
  model: string;
  signal?: AbortSignal;
};
