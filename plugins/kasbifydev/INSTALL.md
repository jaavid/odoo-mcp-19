# KasbifyDev installation

KasbifyDev is packaged as a ChatGPT/Codex plugin that binds to a separately registered ChatGPT App backed by the remote Odoo MCP server.

## 1. Prepare OAuth

Configure Keycloak first. Follow `KEYCLOAK.md` and create the `kasbifydev` realm role plus the MCP client scopes and audience mappers.

Enable OAuth on the Alpic deployment with shared identity and keep it read-only for the initial connection test:

```env
MCP_AUTH_MODE=oidc
MCP_OIDC_IDENTITY_MODE=shared
MCP_OIDC_ISSUER=https://auth.dev.yektaertebat.ir/realms/engineering
MCP_OIDC_REQUIRED_REALM_ROLE=kasbifydev
MCP_OIDC_SHARED_ROLE=readonly
MCP_OIDC_SCOPES=openid,profile,email,mcp:tools,mcp:resources,mcp:prompts
```

The canonical protected resource is:

`https://odoo-mcp-19-cff81cc6.alpic.live/mcp`

## 2. Validate OAuth discovery

From the repository root:

```bash
python plugins/kasbifydev/scripts/check_oauth.py \
  --mcp-origin https://odoo-mcp-19-cff81cc6.alpic.live \
  --issuer https://auth.dev.yektaertebat.ir/realms/engineering
```

Do not proceed until the checker reports the expected resource, issuer, PKCE capability, client-registration capability, and MCP scopes.

## 3. Register the ChatGPT App

Register the remote MCP endpoint as a ChatGPT App with display name `KasbifyDev` and complete its OAuth connection. See `APP_REGISTRATION.md` for the exact values.

After ChatGPT creates the App, copy its canonical App ID.

## 4. Bind the App ID

```bash
python plugins/kasbifydev/scripts/bind_app.py '<CHATGPT_APP_ID>'
python plugins/kasbifydev/scripts/validate_plugin.py
```

`.app.json` contains only the ChatGPT App identifier. Never place an Odoo credential, Keycloak token, MCP API key, cookie, or private key in the plugin package.

## 5. Install or sync the plugin

The plugin manifest is `plugins/kasbifydev/.codex-plugin/plugin.json`; the repository marketplace entry lives under `.agents/plugins/marketplace.json`.

Install/sync it in the supported ChatGPT/Codex surface, then explicitly invoke the app through the plugin.

## 6. Smoke-test read access

Example:

`@KasbifyDev پروژه Engineering را در Odoo بررسی کن و تسک‌های باز را خلاصه کن.`

Confirm that the request authenticates with Keycloak and that only the intended Odoo environment is visible.

## 7. Enable writes deliberately

Only after read-only OAuth works end-to-end, change the hosted deployment to the intended role, for example:

```env
MCP_OIDC_SHARED_ROLE=support
```

The server's strict safety classifier and confirmation-token flow remain active. A write-capable OAuth identity does not bypass those controls.
