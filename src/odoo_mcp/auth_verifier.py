"""Authentication token verification for single- and multi-user deployments.

Supported authentication paths:

* Registry API keys (legacy / non-ChatGPT clients): personal ``cv_odoo_…``
  tokens are hashed and matched against the shared users registry.
* Registry-mapped OIDC: a verified JWT email maps to an active ``users.db``
  identity, preserving personal Odoo credentials and per-user attribution.
* Shared OIDC: a verified Keycloak user is authorized by realm role and/or
  email allowlist, then uses the server's environment-configured Odoo service
  account. This is useful for hosted deployments such as Alpic where the local
  registry database is not mounted.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier

from .users_db import UsersDb

ENV_ADMIN_CLIENT_ID = "env-admin"
_ALLOWED_SHARED_ROLES = frozenset({"readonly", "support", "admin"})


def _registry_scopes(role: str) -> list[str]:
    return ["read"] if role == "readonly" else ["read", "write"]


def _normalized_email(claims: dict, email_claim: str) -> str | None:
    raw_email = claims.get(email_claim)
    if not isinstance(raw_email, str):
        return None
    normalized = raw_email.strip().casefold()
    return normalized or None


def _realm_roles(claims: dict) -> frozenset[str]:
    realm_access = claims.get("realm_access")
    if not isinstance(realm_access, dict):
        return frozenset()
    roles = realm_access.get("roles")
    if not isinstance(roles, list):
        return frozenset()
    return frozenset(role for role in roles if isinstance(role, str))


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
    """Verify an OIDC JWT and bind it to an active users.db identity."""

    def __init__(self, *, users_db: UsersDb, email_claim: str = "email", **kwargs) -> None:
        super().__init__(**kwargs)
        self._db = users_db
        self._email_claim = email_claim

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await super().verify_token(token)
        if verified is None:
            return None

        email = _normalized_email(verified.claims, self._email_claim)
        if email is None:
            self.logger.warning("OIDC token rejected: missing verified %r claim", self._email_claim)
            return None

        identity = await asyncio.to_thread(self._db.lookup_active_user_by_email, email)
        if identity is None:
            self.logger.warning("OIDC token rejected: no unique active registry user for email %r", email)
            return None

        claims = dict(verified.claims)
        claims.update(
            {
                "role": identity.role,
                "name": identity.name,
                "email": identity.email,
                "auth": "oidc-registry",
                "oidc_subject": verified.claims.get("sub"),
                "oidc_client_id": verified.client_id,
            }
        )
        scopes = list(dict.fromkeys([*verified.scopes, *_registry_scopes(identity.role)]))
        return AccessToken(
            token=verified.token,
            client_id=identity.user_id,
            scopes=scopes,
            expires_at=verified.expires_at,
            claims=claims,
        )


class SharedOIDCJWTVerifier(JWTVerifier):
    """Verify OIDC and authorize use of the server's shared Odoo identity.

    This mode deliberately does *not* map to ``users.db``. It is intended for a
    hosted MCP deployment whose Odoo credentials are supplied through
    environment variables. A verified Keycloak identity must still pass the
    configured realm-role and/or email policy before it receives MCP access.

    ``shared_role`` controls only MCP's safety authorization semantics:
    ``readonly`` blocks all side effects, while ``support`` / ``admin`` permit
    writes subject to the normal safety classifier and confirmation gates.
    """

    def __init__(
        self,
        *,
        email_claim: str = "email",
        shared_role: str = "readonly",
        required_realm_role: str | None = None,
        allowed_emails: frozenset[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if shared_role not in _ALLOWED_SHARED_ROLES:
            raise ValueError(
                f"shared_role must be one of {sorted(_ALLOWED_SHARED_ROLES)}, got {shared_role!r}"
            )
        self._email_claim = email_claim
        self._shared_role = shared_role
        self._required_realm_role = required_realm_role.strip() if required_realm_role else None
        self._allowed_emails = frozenset(email.casefold() for email in (allowed_emails or frozenset()))

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await super().verify_token(token)
        if verified is None:
            return None

        subject = verified.claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            self.logger.warning("OIDC token rejected: missing verified subject claim")
            return None

        email = _normalized_email(verified.claims, self._email_claim)
        if email is None:
            self.logger.warning("OIDC token rejected: missing verified %r claim", self._email_claim)
            return None

        if self._required_realm_role and self._required_realm_role not in _realm_roles(verified.claims):
            self.logger.warning(
                "OIDC token rejected: missing required Keycloak realm role %r",
                self._required_realm_role,
            )
            return None

        if self._allowed_emails and email not in self._allowed_emails:
            self.logger.warning("OIDC token rejected: email %r is not in the allowlist", email)
            return None

        claims = dict(verified.claims)
        claims.update(
            {
                "role": self._shared_role,
                "email": email,
                "auth": "oidc-shared",
                "odoo_identity": "service-account",
                "oidc_subject": subject,
                "oidc_client_id": verified.client_id,
            }
        )
        scopes = list(dict.fromkeys([*verified.scopes, *_registry_scopes(self._shared_role)]))
        return AccessToken(
            token=verified.token,
            client_id=subject,
            scopes=scopes,
            expires_at=verified.expires_at,
            claims=claims,
        )
