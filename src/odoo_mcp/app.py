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


def _public_url() -> str:
    """Resolve the public MCP origin, including Alpic's automatic host variable."""
    value = (os.environ.get("MCP_PUBLIC_URL") or os.environ.get("ALPIC_HOST") or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    return value.rstrip("/")


def _build_legacy_verifier(users_db, api_key: str | None):
    """Preserve existing personal/static bearer clients during OAuth migration."""
    if users_db is not None:
        from .auth_verifier import DbTokenVerifier

        return DbTokenVerifier(users_db, static_api_key=api_key)
    if api_key:
        from fastmcp.server.auth import StaticTokenVerifier

        return StaticTokenVerifier(
            tokens={
                api_key: {
                    "client_id": "mcp-client",
                    "scopes": ["read", "write"],
                    "role": "admin",
                    "auth": "static",
                }
            }
        )
    return None


def _get_oidc_auth_provider(users_db, legacy_verifier=None):
    """Build Keycloak OAuth/OIDC auth for ChatGPT-compatible MCP clients.

    Two identity modes are supported:

    ``registry`` maps the verified OIDC email to ``users.db`` and therefore to
    personal Odoo credentials. ``shared`` authorizes the verified Keycloak user
    with a realm role/email policy and then uses the environment-configured Odoo
    service account. The latter is suitable for hosted environments such as
    Alpic where ``users.db`` is not mounted.
    """
    from fastmcp.server.auth import MultiAuth
    from fastmcp.server.auth.providers.keycloak import KeycloakAuthProvider

    from .auth_verifier import RegistryMappedJWTVerifier, SharedOIDCJWTVerifier

    issuer = os.environ.get("MCP_OIDC_ISSUER", "").rstrip("/")
    public_url = _public_url()
    if not issuer:
        raise RuntimeError("MCP_AUTH_MODE=oidc requires MCP_OIDC_ISSUER")
    if not public_url:
        raise RuntimeError("MCP_AUTH_MODE=oidc requires MCP_PUBLIC_URL or ALPIC_HOST")

    audience = os.environ.get("MCP_OIDC_AUDIENCE") or None
    if audience is None:
        logger.warning(
            "MCP_OIDC_AUDIENCE is unset; token audience validation is disabled. "
            "Set it to the exact MCP resource URL before production use."
        )

    jwks_uri = os.environ.get(
        "MCP_OIDC_JWKS_URI",
        f"{issuer}/protocol/openid-connect/certs",
    )
    email_claim = os.environ.get("MCP_OIDC_EMAIL_CLAIM", "email")
    required_scopes = _csv_env(
        "MCP_OIDC_SCOPES",
        "openid,profile,email,mcp:tools,mcp:resources,mcp:prompts",
    )
    identity_mode = os.environ.get("MCP_OIDC_IDENTITY_MODE", "").strip().lower()
    if not identity_mode:
        identity_mode = "registry" if users_db is not None else "shared"

    verifier_kwargs = {
        "jwks_uri": jwks_uri,
        "issuer": issuer,
        "audience": audience,
        "algorithm": os.environ.get("MCP_OIDC_ALGORITHM", "RS256"),
        "required_scopes": required_scopes,
    }

    if identity_mode == "registry":
        if users_db is None:
            raise RuntimeError("MCP_OIDC_IDENTITY_MODE=registry requires USERS_DB_PATH")
        verifier = RegistryMappedJWTVerifier(
            users_db=users_db,
            email_claim=email_claim,
            **verifier_kwargs,
        )
    elif identity_mode == "shared":
        allowed_emails = frozenset(_csv_env("MCP_OIDC_ALLOWED_EMAILS"))
        verifier = SharedOIDCJWTVerifier(
            email_claim=email_claim,
            shared_role=os.environ.get("MCP_OIDC_SHARED_ROLE", "readonly").strip().lower(),
            required_realm_role=os.environ.get("MCP_OIDC_REQUIRED_REALM_ROLE") or None,
            allowed_emails=allowed_emails,
            **verifier_kwargs,
        )
    else:
        raise RuntimeError(
            "Unsupported MCP_OIDC_IDENTITY_MODE="
            f"{identity_mode!r}; expected registry or shared"
        )

    keycloak = KeycloakAuthProvider(
        realm_url=issuer,
        base_url=public_url,
        required_scopes=required_scopes,
        audience=audience,
        token_verifier=verifier,
    )

    if legacy_verifier is not None:
        return MultiAuth(server=keycloak, verifiers=[legacy_verifier])
    return keycloak


def _get_auth_provider():
    """Get the configured authentication provider.

    Modes:
    - ``oidc``: Keycloak OAuth/OIDC, plus optional legacy registry/static tokens.
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
        if os.environ.get("MCP_OIDC_ISSUER"):
            mode = "oidc"
        elif users_db is not None:
            mode = "registry"
        else:
            mode = "static"

    legacy_verifier = _build_legacy_verifier(users_db, api_key)

    if mode == "oidc":
        return _get_oidc_auth_provider(users_db, legacy_verifier=legacy_verifier)

    if mode == "registry":
        if users_db is None:
            raise RuntimeError("MCP_AUTH_MODE=registry requires USERS_DB_PATH")
        return legacy_verifier

    if mode == "static":
        return _build_legacy_verifier(None, api_key)

    if mode == "none":
        return None

    raise RuntimeError(
        f"Unsupported MCP_AUTH_MODE={mode!r}; expected auto, oidc, registry, static, or none"
    )


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
