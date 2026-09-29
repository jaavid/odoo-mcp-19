# KasbifyDev plugin

KasbifyDev is the ChatGPT/Codex plugin wrapper for the remote Odoo 19+ MCP server deployed on Alpic.

## Architecture

```text
ChatGPT / Codex
      │ OAuth 2.1 + PKCE
      ▼
Keycloak realm: engineering
      │ signed access token
      ▼
KasbifyDev MCP on Alpic
      │ Odoo JSON-2
      ▼
Odoo 19+
```

Current MCP deployment:

- Origin: `https://odoo-mcp-19-cff81cc6.alpic.live`
- Protected resource: `https://odoo-mcp-19-cff81cc6.alpic.live/mcp`
- Transport: Streamable HTTP
- Authorization server: `https://auth.dev.yektaertebat.ir/realms/engineering`
- Server: FastMCP 3.4.x

## Authentication modes

KasbifyDev supports two OAuth identity modes:

- `shared`: suitable for Alpic. A verified Keycloak user operates through the Odoo service account configured in the deployment environment. Access is restricted by the `kasbifydev` Keycloak realm role and optionally an email allowlist. It starts read-only by default.
- `registry`: suitable for an internal multi-user deployment with `users.db`. A verified Keycloak email maps to exactly one active registry user and that user's Odoo credential is used.

Existing personal/static MCP tokens may remain enabled during migration through FastMCP `MultiAuth`; ChatGPT itself should use OAuth.

See `KEYCLOAK.md` for the realm scopes, audience mapper, DCR/CIMD notes, and Alpic variables.

## Plugin package

- `.codex-plugin/plugin.json` — plugin identity and UI metadata
- `.app.json` — binding to the ChatGPT App; contains a placeholder until registration
- `skills/odoo-operations/SKILL.md` — schema-first Odoo operating instructions
- `scripts/check_oauth.py` — verifies OAuth/OIDC discovery before ChatGPT registration
- `scripts/bind_app.py` — writes the canonical ChatGPT App ID
- `scripts/validate_plugin.py` — validates the package structure

KasbifyDev intentionally binds to a separately registered ChatGPT App through `.app.json` rather than embedding a remote MCP definition directly in the plugin package.

## Release sequence

1. Configure Keycloak according to `KEYCLOAK.md`.
2. Enable OIDC on the Alpic deployment, initially with `MCP_OIDC_SHARED_ROLE=readonly`.
3. Run `scripts/check_oauth.py` and fix every reported discovery/audience/scope issue.
4. Register the remote MCP as the ChatGPT App `KasbifyDev`.
5. Copy the canonical App ID and run `scripts/bind_app.py`.
6. Run `scripts/validate_plugin.py` and commit the resulting `.app.json`.
7. Install/sync the plugin in the supported ChatGPT surface.
8. Smoke-test a read through `@KasbifyDev`.
9. Only after the read path is stable, enable the intended write role and test the MCP confirmation flow.

## Intended invocation

`@KasbifyDev پروژه Engineering را در Odoo بررسی کن و تسک‌های باز را خلاصه کن.`

For changes, the MCP server's safety classifier remains authoritative. High-impact operations cannot bypass its confirmation-token flow.
