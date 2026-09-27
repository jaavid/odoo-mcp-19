# KasbifyDev plugin

KasbifyDev is the ChatGPT/Codex plugin wrapper for the remote Odoo MCP server deployed on Alpic.

## Backend

- MCP endpoint: `https://odoo-mcp-19-cff81cc6.alpic.live`
- Transport: Streamable HTTP
- Authentication: bearer token / MCP API key as configured on the deployment

## Why the plugin does not declare `.mcp.json`

ChatGPT treats imported plugins that directly declare an MCP server as desktop-only on supported plugin ingestion paths. KasbifyDev is intended to be usable through an OpenAI App binding, so the plugin manifest intentionally contains only skills until the ChatGPT App is registered.

After the remote MCP endpoint is registered as a ChatGPT App, add `plugins/kasbifydev/.app.json` with the resulting app ID and add this field to `.codex-plugin/plugin.json`:

```json
"apps": "./.app.json"
```

Use `app-binding.example.json` as the shape reference.

## ChatGPT App registration

Register the remote endpoint as an MCP-powered app with the display name `KasbifyDev`, scan its tools, configure authentication, and create/publish it according to the workspace policy. Then copy the app ID into `.app.json`.

## Plugin invocation

Once the plugin is installed and its app binding is available, invoke it in supported ChatGPT surfaces with `@KasbifyDev`.
