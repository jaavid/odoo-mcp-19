"""
FastMCP application setup for the Odoo MCP Server.

Creates the FastMCP instance with auth, lifespan, and icon loading.
Other modules import `mcp` from here to register resources, tools, and prompts.
"""

import base64
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from fastmcp import FastMCP
from mcp.types import Icon

from .odoo_client import OdooClient, get_odoo_client

logger = logging.getLogger(__name__)


# ----- Icon Loading -----


def _load_icon() -> Optional[Icon]:
    """Load the Odoo icon from assets as a data URI."""
    icon_path = Path(__file__).parent / "assets" / "odoo_icon.svg"
    try:
        if icon_path.exists():
            icon_data = base64.standard_b64encode(icon_path.read_bytes()).decode()
            return Icon(
                src=f"data:image/svg+xml;base64,{icon_data}",
                mimeType="image/svg+xml",
            )
    except Exception as e:
        logger.warning("Could not load icon: %s", e)
    return None


ODOO_ICON = _load_icon()


# ----- Application Lifespan -----


@dataclass
class AppContext:
    """Application context for the MCP server"""

    odoo: Optional[OdooClient]


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Application lifespan for initialization and cleanup.

    In multi-user mode (USERS_DB_PATH) the env Odoo credentials are
    optional — per-user clients are built lazily from the registry, so a
    missing env config must not prevent startup.
    """
    try:
        odoo_client: Optional[OdooClient] = get_odoo_client()
    except (FileNotFoundError, KeyError) as e:
        if os.environ.get("USERS_DB_PATH"):
            logger.warning("No env Odoo credentials (%s) — multi-user registry mode only", e)
            odoo_client = None
        else:
            raise
    try:
        yield AppContext(odoo=odoo_client)
    finally:
        pass


# ----- Authentication -----


def _csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def _get_oidc_auth_provider(users_db, legacy_verifier=None):
    """Build direct OAuth/OIDC resource-server auth for ChatGPT MCP clients.

    The authorization server is external (Keycloak). FastMCP publishes RFC 9728
    protected-resource metadata; clients then perform OAuth directly against the
    issuer, including Dynamic Client Registration where supported.

    The verified JWT email is mapped back to ``users.db`` so the rest of the
    server continues to resolve the caller's personal Odoo credentials by the
    existing registry user id.
    """
    from pydantic import AnyHttpUrl
    from fastmcp.server.auth import MultiAuth, RemoteAuthProvider

    from .auth_verifier import RegistryMappedJWTVerifier

    issuer = os.environ.get("MCP_OIDC_ISSUER", "").rstrip("/")
    public_url = os.environ.get("MCP_PUBLIC_URL", "").rstrip("/")
    if not issuer:
        raise RuntimeError("MCP_AUTH_MODE=oidc requires MCP_OIDC_ISSUER")
    if not public_url:
        raise RuntimeError("MCP_AUTH_MODE=oidc requires MCP_PUBLIC_URL")
    if users_db is None:
        raise RuntimeError("MCP_AUTH_MODE=oidc requires USERS_DB_PATH for per-user registry mapping")

    jwks_uri = os.environ.get(
        "MCP_OIDC_JWKS_URI",
        f"{issuer}/protocol/openid-connect/certs",
    )
    audience = os.environ.get("MCP_OIDC_AUDIENCE") or None
    email_claim = os.environ.get("MCP_OIDC_EMAIL_CLAIM", "email")
    advertised_scopes = _csv_env("MCP_OIDC_SCOPES", "openid,profile,email")

    verifier = RegistryMappedJWTVerifier(
        users_db=users_db,
        email_claim=email_claim,
        jwks_uri=jwks_uri,
        issuer=issuer,
        audience=audience,
        algorithm=os.environ.get("MCP_OIDC_ALGORITHM", "RS256"),
        # Do not globally require identity scopes in the access token. Keycloak
        # may omit an OpenID request scope from the access token's `scope` claim;
        # the email claim itself is mandatory in RegistryMappedJWTVerifier.
        required_scopes=None,
    )

    remote = RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(issuer)],
        base_url=public_url,
        scopes_supported=advertised_scopes,
        resource_name=os.environ.get("MCP_RESOURCE_NAME", "KasbifyDev Odoo MCP"),
    )

    # OAuth owns discovery routes. Legacy registry/static bearer tokens remain
    # accepted as a secondary verifier so existing integrations do not break.
    if legacy_verifier is not None:
        return MultiAuth(server=remote, verifiers=[legacy_verifier])
    return remote


def _get_auth_provider():
    """Get the configured authentication provider.

    Modes:
    - ``oidc``: direct OAuth/OIDC against Keycloak, plus optional legacy tokens.
    - ``registry``: existing users.db API keys, optionally with MCP_API_KEY fallback.
    - ``static``: MCP_API_KEY only.
    - ``none``: no HTTP auth (primarily stdio/local development).
    - ``auto`` (default): OIDC when MCP_OIDC_ISSUER is set, otherwise preserve
      the existing registry/static behavior.
    """
    api_key = os.environ.get("MCP_API_KEY")

    from .users_db import get_users_db

    users_db = get_users_db()
    mode = os.environ.get("MCP_AUTH_MODE", "auto").strip().lower()
    if mode == "auto":
        mode = "oidc" if os.environ.get("MCP_OIDC_ISSUER") else ("registry" if users_db is not None else "static")

    legacy_verifier = None
    if users_db is not None:
        from .auth_verifier import DbTokenVerifier

        legacy_verifier = DbTokenVerifier(users_db, static_api_key=api_key)

    if mode == "oidc":
        return _get_oidc_auth_provider(users_db, legacy_verifier=legacy_verifier)

    if mode == "registry":
        if legacy_verifier is None:
            raise RuntimeError("MCP_AUTH_MODE=registry requires USERS_DB_PATH")
        return legacy_verifier

    if mode == "static":
        if not api_key:
            return None
        from fastmcp.server.auth import StaticTokenVerifier

        return StaticTokenVerifier(
            tokens={
                api_key: {
                    "client_id": "mcp-client",
                    "scopes": ["read", "write"],
                }
            }
        )

    if mode == "none":
        return None

    raise RuntimeError(f"Unsupported MCP_AUTH_MODE={mode!r}; expected auto, oidc, registry, static, or none")


# ----- Create MCP Server -----

_auth = _get_auth_provider()
_icons = [ODOO_ICON] if ODOO_ICON else None
_server_name = os.environ.get("MCP_SERVER_NAME", "KasbifyDev")
_website_url = os.environ.get("MCP_WEBSITE_URL", "https://github.com/jaavid/odoo-mcp-19")

mcp = FastMCP(
    _server_name,
    lifespan=app_lifespan,
    auth=_auth,
    website_url=_website_url,
    icons=_icons,
)


# ----- Per-user skill visibility (multi-user mode only) -----


def _register_skill_visibility() -> None:
    from .users_db import get_users_db

    users_db = get_users_db()
    if users_db is not None:
        from .skill_visibility import SkillVisibilityMiddleware

        mcp.add_middleware(SkillVisibilityMiddleware(users_db))


_register_skill_visibility()
