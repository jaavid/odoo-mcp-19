"""Multi-user bearer token verification backed by the shared registry.

Each colleague authenticates with a personal ``cv_odoo_…`` key; the sha256
of the presented token is matched against the registry (CLORAG-managed
users.db). The optional static MCP_API_KEY keeps working as a fallback and
maps to a synthetic admin identity that uses the env-based Odoo client.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from contextvars import ContextVar

from fastmcp.server.auth import AccessToken, TokenVerifier

from .users_db import UsersDb

ENV_ADMIN_CLIENT_ID = "env-admin"

# FastMCP normally exposes the current identity through get_access_token().
# Some sync tool/resource bridges in FastMCP 3.x can lose that dependency
# context even though ordinary ContextVars still propagate into the worker
# thread. Keep the already-verified identity in our own request context as a
# fallback so per-user Odoo resolution never silently drops to env credentials.
_verified_access_token: ContextVar[AccessToken | None] = ContextVar(
    "odoo_mcp_verified_access_token", default=None
)


def get_verified_access_token() -> AccessToken | None:
    """Return the token most recently verified in the current request context."""
    return _verified_access_token.get()


class DbTokenVerifier(TokenVerifier):
    """Verify bearer tokens against the shared per-user registry."""

    def __init__(self, users_db: UsersDb, static_api_key: str | None = None) -> None:
        super().__init__()
        self._db = users_db
        self._static = static_api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        if self._static and hmac.compare_digest(token, self._static):
            access_token = AccessToken(
                token=token,
                client_id=ENV_ADMIN_CLIENT_ID,
                scopes=["read", "write"],
                claims={"role": "admin", "auth": "static"},
            )
            _verified_access_token.set(access_token)
            return access_token

        key_hash = hashlib.sha256(token.encode()).hexdigest()
        # SQLite lookup off the event loop
        identity = await asyncio.to_thread(self._db.lookup_api_key, key_hash)
        if identity is None:
            # Clear any previous value in case a request execution context is
            # reused by the host. An invalid token must never inherit identity.
            _verified_access_token.set(None)
            return None

        scopes = ["read"] if identity.role == "readonly" else ["read", "write"]
        access_token = AccessToken(
            token=token,
            client_id=identity.user_id,
            scopes=scopes,
            claims={
                "role": identity.role,
                "name": identity.name,
                "email": identity.email,
                "auth": "registry",
            },
        )
        _verified_access_token.set(access_token)
        return access_token
