# KasbifyDev release checklist

## MCP and plugin package

- [x] Remote MCP deployed and healthy on Alpic
- [x] Server identity defaults to `KasbifyDev`
- [x] Plugin marketplace entry exists
- [x] Plugin manifest exists and references `.app.json`
- [x] Odoo operations skill exists
- [x] ChatGPT App binding placeholder exists
- [x] App-ID binding helper exists
- [x] Structural plugin validator exists
- [x] Plugin CI validation exists

## OAuth implementation

- [x] Keycloak/OIDC resource-server mode implemented
- [x] FastMCP Keycloak provider used for OAuth discovery/DCR
- [x] Legacy bearer clients retained through `MultiAuth`
- [x] Hosted shared-Odoo identity mode implemented
- [x] Per-user registry identity mode implemented
- [x] Shared mode defaults to read-only
- [x] Required Keycloak realm-role policy implemented
- [x] JWT audience is bound to the protected MCP resource URL
- [x] OIDC verifier tests pass on supported Python versions
- [x] OAuth discovery readiness checker exists

## External configuration still required

- [ ] Create/assign Keycloak realm role `kasbifydev`
- [ ] Create optional Keycloak scopes `mcp:tools`, `mcp:resources`, `mcp:prompts`
- [ ] Add audience mappers for `https://odoo-mcp-19-cff81cc6.alpic.live/mcp`
- [ ] Confirm Keycloak DCR or CIMD policy permits the ChatGPT OAuth client
- [ ] Configure Alpic OIDC environment variables with shared role `readonly`
- [ ] Run `scripts/check_oauth.py` successfully against the live deployment

## ChatGPT binding

- [ ] Register `KasbifyDev` as the ChatGPT App in a supported ChatGPT surface
- [ ] Complete OAuth login through Keycloak
- [ ] Bind the canonical ChatGPT App ID into `.app.json`
- [ ] Run `scripts/validate_plugin.py` successfully with the real App ID
- [ ] Install/sync the plugin
- [ ] Smoke-test read-only invocation with `@KasbifyDev`

## Write enablement

- [ ] Decide shared-service-account vs per-user Odoo attribution for production writes
- [ ] Enable the intended OAuth write role only after read-only smoke tests pass
- [ ] Smoke-test a low-impact confirmed write
- [ ] Verify post-write read-back and Odoo attribution
- [ ] Verify high-risk operations still require the server confirmation-token flow
