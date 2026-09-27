# Registering KasbifyDev in ChatGPT

The repository cannot manufacture a ChatGPT App ID. The App is an account/workspace object created by ChatGPT, then referenced by this plugin.

Use these values when registering the app:

- Name: `KasbifyDev`
- MCP endpoint: `https://odoo-mcp-19-cff81cc6.alpic.live`
- Transport: Streamable HTTP
- Purpose: Odoo 19 project, CRM, calendar, task and operational access through the existing MCP tools

After registration, replace `REPLACE_WITH_CHATGPT_APP_ID` in `.app.json` using `scripts/bind_app.py`.

The MCP backend already handles authentication independently. Never place Odoo credentials or MCP bearer tokens in the plugin manifest.
