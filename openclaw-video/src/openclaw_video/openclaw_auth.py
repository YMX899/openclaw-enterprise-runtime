from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:  # pragma: no cover - exercised in the production image/venv
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - keeps system-python unit tests importable
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class OpenClawAuthenticationError(PermissionError):
    """Raised when an OpenClaw username/password login fails."""


class OpenClawAuthDependencyError(RuntimeError):
    """Raised when password login is configured but dependencies are missing."""


@dataclass(frozen=True)
class OpenClawPasswordIdentity:
    profile: dict[str, Any]
    workspaces: dict[str, Any]


class CompositeOpenClawAuthenticator:
    def __init__(self, *authenticators: Any) -> None:
        self.authenticators = [authenticator for authenticator in authenticators if authenticator is not None]

    def authenticate(self, account: str, password: str) -> OpenClawPasswordIdentity:
        for authenticator in self.authenticators:
            try:
                return authenticator.authenticate(account, password)
            except OpenClawAuthenticationError:
                continue
        raise OpenClawAuthenticationError("login failed")


def default_openclaw_authenticator() -> Any | None:
    """Use Huahuo's frontend user system as the OpenClaw password authority."""

    return HuahuoPasswordAuthenticator(
        os.environ.get("HUAHUO_FRONT_BASE", "https://www.huahuoai.com"),
        tenant_id=os.environ.get("HUAHUO_FRONT_TENANT_ID", "huahuo-front"),
    )


def compare_dify_password(password: str, password_hashed_base64: str | None, salt_base64: str | None) -> bool:
    """Return True when a plaintext password matches Dify's stored hash."""

    if not password or not password_hashed_base64 or not salt_base64:
        return False
    try:
        salt = base64.b64decode(salt_base64)
        expected = base64.b64decode(password_hashed_base64)
    except (binascii.Error, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 10000)
    actual_hex = binascii.hexlify(actual)
    return hmac.compare_digest(actual_hex, expected)


def parse_account_aliases(raw: str | None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    if not raw:
        return aliases
    for item in raw.split(","):
        source, sep, target = item.partition("=")
        if sep and source.strip() and target.strip():
            aliases[source.strip()] = target.strip()
    return aliases


class DifyDatabasePasswordAuthenticator:
    """Validate OpenClaw login credentials against Dify's accounts table."""

    def __init__(
        self,
        conninfo: str | None = None,
        *,
        account_aliases: dict[str, str] | None = None,
        connect_kwargs: dict[str, str] | None = None,
        connection_factory: Any | None = None,
    ) -> None:
        self.conninfo = conninfo
        self.account_aliases = account_aliases or {}
        self.connect_kwargs = connect_kwargs or {}
        self.connection_factory = connection_factory
        if not conninfo and not connection_factory:
            if not self.connect_kwargs:
                raise ValueError("conninfo, connect_kwargs, or connection_factory is required")

    @classmethod
    def from_environment(cls) -> DifyDatabasePasswordAuthenticator | None:
        conninfo = os.environ.get("DIFY_AUTH_DATABASE_URL", "").strip()
        kwargs = {
            "host": os.environ.get("DIFY_AUTH_DB_HOST", "").strip(),
            "port": os.environ.get("DIFY_AUTH_DB_PORT", "").strip(),
            "dbname": os.environ.get("DIFY_AUTH_DB_NAME", "").strip(),
            "user": os.environ.get("DIFY_AUTH_DB_USER", "").strip(),
            "password": os.environ.get("DIFY_AUTH_DB_PASSWORD", ""),
        }
        if not conninfo and not all(kwargs.values()):
            return None
        return cls(
            conninfo or None,
            account_aliases=parse_account_aliases(os.environ.get("OPENCLAW_LOGIN_ACCOUNT_ALIASES")),
            connect_kwargs=kwargs if not conninfo else None,
        )

    def _connect(self) -> Any:
        if self.connection_factory:
            return self.connection_factory()
        if psycopg is None or dict_row is None:
            raise OpenClawAuthDependencyError("psycopg[binary] is required for OpenClaw password login")
        return psycopg.connect(self.conninfo or "", row_factory=dict_row, **self.connect_kwargs)

    def authenticate(self, account: str, password: str) -> OpenClawPasswordIdentity:
        normalized_account = account.strip()
        lookup_account = self.account_aliases.get(normalized_account, normalized_account)
        if not lookup_account or not password:
            raise OpenClawAuthenticationError("login failed")
        with self._connect() as conn:
            with conn.cursor() as cur:
                account_row = self._find_account(cur, lookup_account)
                if not account_row:
                    raise OpenClawAuthenticationError("login failed")
                status = str(account_row.get("status") or "")
                if status not in {"active", "pending"}:
                    raise OpenClawAuthenticationError("login failed")
                if not compare_dify_password(
                    password,
                    account_row.get("password"),
                    account_row.get("password_salt"),
                ):
                    raise OpenClawAuthenticationError("login failed")
                tenants = self._tenant_rows(cur, str(account_row["id"]))
        if not tenants:
            raise OpenClawAuthenticationError("login failed")
        selected_tenant_id = self._selected_tenant_id(tenants)
        return OpenClawPasswordIdentity(
            profile={"id": str(account_row["id"])},
            workspaces={
                "data": [
                    {"id": str(row["id"]), "current": str(row["id"]) == selected_tenant_id}
                    for row in tenants
                ]
            },
        )

    def _find_account(self, cur: Any, account: str) -> dict[str, Any] | None:
        if _UUID_RE.fullmatch(account):
            cur.execute(
                """
                SELECT id, email, name, password, password_salt, status
                FROM accounts
                WHERE lower(email) = lower(%s)
                   OR name = %s
                   OR id = %s
                ORDER BY
                  CASE
                    WHEN lower(email) = lower(%s) THEN 0
                    WHEN name = %s THEN 1
                    WHEN id = %s THEN 2
                    ELSE 3
                  END
                LIMIT 1
                """,
                (account, account, account, account, account, account),
            )
            return cur.fetchone()
        cur.execute(
            """
            SELECT id, email, name, password, password_salt, status
            FROM accounts
            WHERE lower(email) = lower(%s)
               OR name = %s
            ORDER BY
              CASE
                WHEN lower(email) = lower(%s) THEN 0
                WHEN name = %s THEN 1
                ELSE 3
              END
            LIMIT 1
            """,
            (account, account, account, account),
        )
        return cur.fetchone()

    def _tenant_rows(self, cur: Any, account_id: str) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT t.id, taj.current, taj.created_at
            FROM tenant_account_joins taj
            JOIN tenants t ON t.id = taj.tenant_id
            WHERE taj.account_id = %s
              AND t.status = 'normal'
            ORDER BY taj.current DESC, taj.created_at ASC
            """,
            (account_id,),
        )
        return list(cur.fetchall())

    @staticmethod
    def _selected_tenant_id(rows: list[dict[str, Any]]) -> str:
        for row in rows:
            if row.get("current") is True:
                return str(row["id"])
        return str(rows[0]["id"])


class HuahuoPasswordAuthenticator:
    """Validate OpenClaw login credentials against Huahuo's frontend login API."""

    def __init__(
        self,
        base_url: str,
        *,
        tenant_id: str = "huahuo-front",
        timeout_seconds: float = 10.0,
        transport: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def authenticate(self, account: str, password: str) -> OpenClawPasswordIdentity:
        account = account.strip()
        if not account or not password:
            raise OpenClawAuthenticationError("login failed")
        if httpx is None:
            raise OpenClawAuthDependencyError("httpx is required for Huahuo password login")
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                login_response = client.post(
                    "/api/login",
                    headers=self._headers(access_token=""),
                    json={"loginName": account, "password": password},
                )
                if login_response.status_code in {401, 403}:
                    raise OpenClawAuthenticationError("login failed")
                login_response.raise_for_status()
                login_payload = login_response.json()
                access_token = self._access_token(login_payload)
                if not access_token:
                    raise OpenClawAuthenticationError("login failed")
                profile_response = client.get(
                    "/api/front/user/queryUserInfo",
                    headers=self._headers(access_token=access_token),
                )
                if profile_response.status_code in {401, 403}:
                    raise OpenClawAuthenticationError("login failed")
                profile_response.raise_for_status()
                profile_payload = profile_response.json()
        except OpenClawAuthenticationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenClawAuthenticationError("login failed") from exc
        data = profile_payload.get("data") if isinstance(profile_payload, dict) else None
        if not isinstance(profile_payload, dict) or profile_payload.get("status") != 1 or not isinstance(data, dict):
            raise OpenClawAuthenticationError("login failed")
        account_id = data.get("id") or data.get("userId") or data.get("loginName") or data.get("mobile") or data.get("email")
        if account_id in (None, ""):
            raise OpenClawAuthenticationError("login failed")
        return OpenClawPasswordIdentity(
            profile={"id": f"huahuo:{account_id}"},
            workspaces={"data": [{"id": self.tenant_id, "current": True}]},
        )

    @staticmethod
    def _access_token(payload: Any) -> str:
        if not isinstance(payload, dict) or payload.get("status") != 1:
            return ""
        data = payload.get("data")
        if isinstance(data, dict):
            return str(data.get("accessToken") or "")
        return str(payload.get("accessToken") or "")

    @staticmethod
    def _headers(*, access_token: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": "https://www.huahuoai.com",
            "Referer": "https://www.huahuoai.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            ),
        }
        if access_token is not None:
            headers["Authorization"] = HuahuoPasswordAuthenticator._authorization_header(access_token or "null")
        return headers

    @staticmethod
    def _authorization_header(access_token: str) -> str:
        app_uuid = uuid.uuid4().hex
        app_time_ms = int(time.time() * 1000)
        first = hashlib.md5(("WEB" + app_uuid).encode("utf-8")).hexdigest().upper()
        app_sign = hashlib.md5((first + str(app_time_ms)).encode("utf-8")).hexdigest().upper()
        payload = urlencode(
            {
                "appVersion": "1.0.1",
                "appType": "WEB",
                "appUuid": app_uuid,
                "appTime": str(app_time_ms),
                "appSign": app_sign,
                "token": access_token,
            }
        )
        encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        return "Bearer " + encoded
