# KasbifyDev installation

KasbifyDev is packaged as a ChatGPT/Codex plugin that binds to a separately registered ChatGPT App.

## Backend

Remote MCP endpoint:

`https://odoo-mcp-19-cff81cc6.alpic.live`

The MCP transport is Streamable HTTP and is deployed on Alpic.

## 1. Register the ChatGPT App

Create a ChatGPT App backed by the remote MCP endpoint above. Give it the user-facing name `KasbifyDev`.

After ChatGPT creates the app, copy its canonical App ID.

## 2. Bind the App ID

From the repository root:

```bash
python plugins/kasbifydev/scripts/bind_app.py '<CHATGPT_APP_ID>'
python plugins/kasbifydev/scripts/validate_plugin.py
```

Do not commit a credential, bearer token, Odoo password, or API key into `.app.json`. The file contains only the ChatGPT App identifier.

## 3. Plugin files

- `.codex-plugin/plugin.json`: plugin identity and UI metadata
- `.app.json`: binding from the plugin to the registered ChatGPT App
- `skills/`: operational guidance used when KasbifyDev is invoked

## 4. Expected invocation

Once the app/plugin is installed in a supported ChatGPT surface, use it explicitly, for example:

`@KasbifyDev پروژه Engineering را در Odoo بررسی کن و تسک‌های باز را خلاصه کن.`

For mutations, the MCP server's safety layer remains authoritative. Operations classified as dangerous must pass the server-side confirmation-token flow.
