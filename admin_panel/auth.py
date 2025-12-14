"""Authentication helpers for the admin panel server."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional

from aiohttp import web

SESSION_COOKIE_NAME = "mb_admin_session"


@dataclass(frozen=True)
class AdminIdentity:
    slug: str
    display: str
    token: str


@dataclass
class AuthResult:
    ok: bool
    identity: Optional[AdminIdentity] = None
    set_cookie: Optional[str] = None


class AdminAuthManager:
    """Encapsulates single/multi-admin authentication logic."""

    def __init__(
        self,
        *,
        access_token: Optional[str],
        admin_accounts: Optional[Dict[str, Dict[str, str]]],
        cookie_secret: Optional[str],
        session_ttl: int,
    ) -> None:
        self._token = access_token
        self._session_cookie = SESSION_COOKIE_NAME
        self._session_ttl = max(300, session_ttl)
        self._accounts = self._build_accounts(admin_accounts or {})
        self._token_lookup: Dict[str, AdminIdentity] = {
            identity.token: identity for identity in self._accounts.values()
        }
        self._cookie_secret: Optional[str] = None
        if self._token_lookup:
            seed = cookie_secret or access_token or secrets.token_hex(32)
            self._cookie_secret = seed

    # ------------------------------------------------------------------
    def multi_admin_enabled(self) -> bool:
        return bool(self._token_lookup)

    def single_access_token(self) -> Optional[str]:
        if self.multi_admin_enabled():
            return None
        return self._token

    def authorize(self, request: web.Request) -> AuthResult:
        if self.multi_admin_enabled():
            return self._authorize_multi(request)
        return self._authorize_single(request)

    def attach_cookies(self, response: web.StreamResponse, auth: AuthResult) -> None:
        if not self.multi_admin_enabled():
            return
        if auth.set_cookie:
            response.set_cookie(
                self._session_cookie,
                auth.set_cookie,
                max_age=self._session_ttl,
                httponly=True,
                samesite="Lax",
            )

    def logout_response(self) -> web.Response:
        response = web.Response(status=302, headers={"Location": "/admin"})
        response.del_cookie(self._session_cookie)
        return response

    # ------------------------------------------------------------------
    def _build_accounts(self, raw_accounts: Dict[str, Dict[str, str]]) -> Dict[str, AdminIdentity]:
        accounts: Dict[str, AdminIdentity] = {}
        for slug, payload in raw_accounts.items():
            token = (payload or {}).get("token")
            display = (payload or {}).get("display") or slug
            normalized_slug = (slug or "").strip()
            if not normalized_slug or not token:
                continue
            accounts[normalized_slug] = AdminIdentity(normalized_slug, display, token)
        return accounts

    def _authorize_single(self, request: web.Request) -> AuthResult:
        if not self._token:
            return AuthResult(ok=True)
        header_token = request.headers.get("X-Admin-Token")
        query_token = request.rel_url.query.get("token")
        if header_token == self._token or query_token == self._token:
            return AuthResult(ok=True)
        return AuthResult(ok=False)

    def _authorize_multi(self, request: web.Request) -> AuthResult:
        cookie_value = request.cookies.get(self._session_cookie)
        identity = self._validate_session_cookie(cookie_value)
        if identity:
            return AuthResult(ok=True, identity=identity)

        header_token = request.headers.get("X-Admin-Token")
        token = header_token or request.rel_url.query.get("token")
        if not token:
            return AuthResult(ok=False)
        identity = self._token_lookup.get(token)
        if not identity:
            return AuthResult(ok=False)
        cookie_payload = self._build_session_cookie(identity)
        return AuthResult(ok=True, identity=identity, set_cookie=cookie_payload)

    def _build_session_cookie(self, identity: AdminIdentity) -> Optional[str]:
        if not self._cookie_secret:
            return None
        expires_at = int(time.time()) + self._session_ttl
        payload = f"{identity.slug}:{expires_at}"
        signature = hmac.new(self._cookie_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}:{signature}"

    def _validate_session_cookie(self, cookie_value: Optional[str]) -> Optional[AdminIdentity]:
        if not cookie_value or not self._cookie_secret:
            return None
        try:
            slug, expires_raw, signature = cookie_value.split(":", 2)
            expires_at = int(expires_raw)
        except ValueError:
            return None
        if expires_at < int(time.time()):
            return None
        payload = f"{slug}:{expires_at}"
        expected = hmac.new(self._cookie_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        return self._accounts.get(slug)


__all__ = [
    "AdminAuthManager",
    "AdminIdentity",
    "AuthResult",
    "SESSION_COOKIE_NAME",
]
