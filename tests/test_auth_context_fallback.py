"""Regression tests for authenticated identity across sync worker bridges."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import anyio
import pytest

import odoo_mcp.auth_verifier as auth_verifier
import odoo_mcp.user_clients as user_clients


@pytest.mark.anyio
async def test_static_verified_token_is_saved_in_request_context():
    """A valid static admin key becomes the request-local verified identity."""
    verifier = auth_verifier.DbTokenVerifier(MagicMock(), static_api_key="secret")

    token = await verifier.verify_token("secret")

    assert token is not None
    assert auth_verifier.get_verified_access_token() is token
    assert token.client_id == auth_verifier.ENV_ADMIN_CLIENT_ID


@pytest.mark.anyio
async def test_invalid_token_clears_previous_verified_identity():
    """An invalid registry token cannot inherit a previously verified identity."""
    stale = SimpleNamespace(client_id="stale-user", claims={"role": "member"})
    reset_token = auth_verifier._verified_access_token.set(stale)
    try:
        users_db = MagicMock()
        users_db.lookup_api_key.return_value = None
        verifier = auth_verifier.DbTokenVerifier(users_db)

        assert await verifier.verify_token("invalid") is None
        assert auth_verifier.get_verified_access_token() is None
    finally:
        auth_verifier._verified_access_token.reset(reset_token)


@pytest.mark.anyio
async def test_registry_lookup_failure_clears_previous_verified_identity():
    """A registry exception must fail closed instead of retaining stale identity."""
    stale = SimpleNamespace(client_id="stale-user", claims={"role": "member"})
    reset_token = auth_verifier._verified_access_token.set(stale)
    try:
        users_db = MagicMock()
        users_db.lookup_api_key.side_effect = RuntimeError("registry unavailable")
        verifier = auth_verifier.DbTokenVerifier(users_db)

        with pytest.raises(RuntimeError, match="registry unavailable"):
            await verifier.verify_token("candidate")
        assert auth_verifier.get_verified_access_token() is None
    finally:
        auth_verifier._verified_access_token.reset(reset_token)


@pytest.mark.anyio
async def test_verified_identity_survives_anyio_worker_thread(monkeypatch):
    """Matches the sync read_resource/tool execution boundary seen in production."""
    verified = SimpleNamespace(client_id="registry-user", claims={"role": "member"})
    reset_token = auth_verifier._verified_access_token.set(verified)
    try:
        # Simulate FastMCP 3.x losing its dependency-local access token in the
        # sync bridge while ordinary ContextVars are still propagated by AnyIO.
        import fastmcp.server.dependencies as dependencies

        monkeypatch.setattr(dependencies, "get_access_token", lambda: None)

        resolved = await anyio.to_thread.run_sync(user_clients._safe_get_access_token)

        assert resolved is verified
    finally:
        auth_verifier._verified_access_token.reset(reset_token)
