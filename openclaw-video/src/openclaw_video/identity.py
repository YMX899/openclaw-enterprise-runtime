from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Iterable


class IdentityError(ValueError):
    """Raised when Dify identity data cannot be safely resolved."""


@dataclass(frozen=True)
class DifyPrincipal:
    account_id: str
    tenant_id: str
    principal_id: str


def _field(obj: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in obj and obj[name] not in (None, ""):
            return obj[name]
    return None


def extract_account_id(profile: dict[str, Any]) -> str:
    account_id = _field(profile, "id", "account_id", "accountId")
    if isinstance(profile.get("account"), dict):
        account_id = account_id or _field(profile["account"], "id", "account_id")
    if not account_id:
        raise IdentityError("Dify profile did not contain an account id")
    return str(account_id)


def _workspace_items(workspaces: Any) -> list[dict[str, Any]]:
    if isinstance(workspaces, dict):
        candidates = workspaces.get("data") or workspaces.get("items") or workspaces.get("workspaces")
    else:
        candidates = workspaces
    if not isinstance(candidates, Iterable) or isinstance(candidates, (str, bytes)):
        raise IdentityError("Dify workspaces response is not a list")
    return [item for item in candidates if isinstance(item, dict)]


def select_current_workspace(workspaces: Any) -> dict[str, Any]:
    items = _workspace_items(workspaces)
    current = current_workspace_candidates(items)
    if len(current) != 1:
        raise IdentityError(f"expected exactly one current workspace, got {len(current)}")
    return current[0]


def current_workspace_candidates(workspaces: Any) -> list[dict[str, Any]]:
    items = _workspace_items(workspaces)
    return [
        item
        for item in items
        if item.get("current") is True
        or item.get("is_current") is True
        or item.get("isCurrent") is True
        or item.get("role") == "current"
    ]


def current_workspace_count(workspaces: Any) -> int:
    return len(current_workspace_candidates(workspaces))


def extract_tenant_id(workspaces: Any) -> str:
    workspace = select_current_workspace(workspaces)
    tenant_id = _field(workspace, "id", "tenant_id", "tenantId", "workspace_id")
    if not tenant_id:
        raise IdentityError("current workspace did not contain a tenant id")
    return str(tenant_id)


def hmac_sha256_hex(secret: str, value: str) -> str:
    if not secret:
        raise IdentityError("identity secret is required")
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def derive_principal(secret: str, profile: dict[str, Any], workspaces: Any) -> DifyPrincipal:
    account_id = extract_account_id(profile)
    tenant_id = extract_tenant_id(workspaces)
    logical_user = f"dify:{tenant_id}:{account_id}"
    principal_id = hmac_sha256_hex(secret, logical_user)
    return DifyPrincipal(account_id=account_id, tenant_id=tenant_id, principal_id=principal_id)


def derive_openclaw_routing_user(secret: str, principal_id: str, bridge_session_id: str) -> str:
    if not principal_id or not bridge_session_id:
        raise IdentityError("principal_id and bridge_session_id are required")
    return hmac_sha256_hex(secret, f"{principal_id}:{bridge_session_id}")
