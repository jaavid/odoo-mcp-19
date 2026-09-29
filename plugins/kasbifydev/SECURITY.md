# Security model

KasbifyDev does not embed Odoo credentials in the plugin package.

Authentication is enforced by the remote MCP server. The server supports a static MCP API key and its existing multi-user registry mode. Authorization and Odoo record rules remain server-side.

Write-capable MCP tools retain the server's safety classification and confirmation-token flow. The plugin must not bypass, emulate, or weaken those checks.

Never commit any of the following into this directory:

- Odoo username/password or API credentials
- MCP bearer/API tokens
- session cookies
- private keys
- user registry databases

`.app.json` contains only the canonical ChatGPT App identifier after registration; it is not a credential.
