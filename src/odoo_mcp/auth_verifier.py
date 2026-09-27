"""Authentication token verification for single- and multi-user deployments.

Two authentication paths are supported:

* Registry API keys (legacy / non-ChatGPT clients): personal ``cv_odoo_…``
  tokens are hashed and matched against the shared users registry.
* OIDC JWTs (ChatGPT and other OAuth-capable MCP clients): the JWT is verified
  against the configured issuer/JWKS, then its verified email claim is mapped
  to an active registry user. The registry user id becomes FastMCP's
  ``client_id`` so the existing per-user Odoo credential resolution continues
  to work unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier

from .users_db import UsersDb

ENV_ADMIN_CLIENT_ID = "env-admin"


def _registry_scopes(role: str) -> list[str]:
    return ["read"] if role == "readonly" else ["read", "write"]


class DbTokenVerifier(TokenVerifier):
    """Verify bearer tokens against the shared per-user registry."""

    def __init__(self, users_db: UsersDb, static_api_key: str | None = None) -> None:
        super().__init__()
        self._db = users_db
        self._static = static_api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        if self._static and hmac.compare_digest(token, self._static):
            return AccessToken(
                token=token,
                client_id=ENV_ADMIN_CLIENT_ID,
                scopes=["read", "write"],
                claims={"role": "admin", "auth": "static"},
            )
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        # SQLite lookup off the event loop
        identity = await asyncio.to_thread(self._db.lookup_api_key, key_hash)
        if identity is None:
            return None
        return AccessToken(
            token=token,
            client_id=identity.user_id,
            scopes=_registry_scopes(identity.role),
            claims={
                "role": identity.role,
                "name": identity.name,
                "email": identity.email,
                "auth": "registry",
            },
        )


class RegistryMappedJWTVerifier(JWTVerifier):
    """Verify an OIDC JWT and bind it to an active users.db identity.

    Signature, issuer, expiry, optional audience, and any configured JWT scopes
    are validated by :class:`JWTVerifier` first. Only then is the verified email
    claim used to resolve a local registry user. This prevents an OAuth login
    from bypassing the registry's account enable/disable state or per-user Odoo
    credential mapping.
    """

    def __init__(self, *, users_db: UsersDb, email_claim: str = "email", **kwargs) -> None:
        super().__init__(**kwargs)
        self._db = users_db
        self._email_claim = email_claim

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await super().verify_token(token)
        if verified is None:
            return None

        raw_email = verified.claims.get(self._email_claim)
        if not isinstance(raw_email, str) or not raw_email.strip():
            self.logger.warning("OIDC token rejected: missing verified %r claim", self._email_claim)
            return None

        identity = await asyncio.to_thread(self._db.lookup_active_user_by_email, raw_email)
        if identity is None:
            self.logger.warning("OIDC token rejected: no unique active registry user for email %r", raw_email)
            return None

        claims = dict(verified.claims)
        claims.update(
            {
                "role": identity.role,
                "name": identity.name,
                "email": identity.email,
                "auth": "oidc",
                "oidc_subject": verified.claims.get("sub"),
                "oidc_client_id": verified.client_id,
            }
        )

        # Preserve upstream OAuth/OIDC scopes for observability while adding the
        # registry authorization scopes expected by the existing MCP safety layer.
        scopes = list(dict.fromkeys([*verified.scopes, *_registry_scopes(identity.role)]))
        return AccessToken(
            token=verified.token,
            client_id=identity.user_id,
            scopes=scopes,
            expires_at=verified.expires_at,
            claims=claims,
        )
