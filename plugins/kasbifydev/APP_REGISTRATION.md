# Registering KasbifyDev in ChatGPT

The ChatGPT App is an account/workspace object. This repository can prepare the MCP backend and plugin package, but the App itself must be created in a supported ChatGPT surface and its canonical App ID then bound into `.app.json`.

## Registration values

Use:

- Name: `KasbifyDev`
- MCP origin: `https://odoo-mcp-19-cff81cc6.alpic.live`
- MCP resource endpoint: `https://odoo-mcp-19-cff81cc6.alpic.live/mcp`
- Transport: Streamable HTTP
- Authentication: OAuth 2.1 / OIDC through Keycloak
- Authorization server: `https://auth.dev.yektaertebat.ir/realms/engineering`
- Purpose: Odoo 19 project, task, CRM, calendar, contact, inspection, troubleshooting, and controlled mutation workflows

Before registration, run `scripts/check_oauth.py`; ChatGPT must be able to discover the protected-resource metadata and the Keycloak authorization-server metadata without a private network dependency.

## Authentication expectations

ChatGPT should authenticate the human user with OAuth. Do not configure the plugin with the Odoo credential or the legacy static MCP bearer token.

For the initial App registration, keep `MCP_OIDC_SHARED_ROLE=readonly`. After the connection and read smoke test are proven, write capability can be deliberately enabled on the server while retaining the MCP safety confirmation gates.

## Bind the resulting App ID

After ChatGPT creates the App, run:

```bash
python plugins/kasbifydev/scripts/bind_app.py '<CHATGPT_APP_ID>'
python plugins/kasbifydev/scripts/validate_plugin.py
```

Commit only the resulting App identifier. Tokens and credentials remain outside the repository.
