# KasbifyDev OAuth with Keycloak

KasbifyDev uses the MCP authorization model: the MCP server is the protected resource and Keycloak is the authorization server. ChatGPT authenticates the human user with OAuth/OIDC and sends the resulting bearer access token to the MCP server.

## Current deployment values

For the current KasbifyDev deployment:

- MCP origin: `https://odoo-mcp-19-cff81cc6.alpic.live`
- FastMCP protected resource: `https://odoo-mcp-19-cff81cc6.alpic.live/mcp`
- Keycloak realm issuer: `https://auth.dev.yektaertebat.ir/realms/engineering`
- Recommended Keycloak realm role: `kasbifydev`
- MCP scopes: `mcp:tools`, `mcp:resources`, `mcp:prompts`

FastMCP derives the protected resource from the public origin plus its streamable-HTTP path (`/mcp` by default). The JWT verifier uses the same resource URL as the default expected audience.

## 1. Restrict who may use KasbifyDev

In realm `engineering`, create the realm role:

`kasbifydev`

Assign it only to users who should be allowed to connect to this MCP server.

The hosted/shared deployment defaults to requiring this role. You may additionally set `MCP_OIDC_ALLOWED_EMAILS`, but the realm role should remain the primary policy.

## 2. Create MCP client scopes

Create these Keycloak client scopes as **Optional**:

- `mcp:tools`
- `mcp:resources`
- `mcp:prompts`

On each client scope add an **Audience** protocol mapper with:

- Included Custom Audience: `https://odoo-mcp-19-cff81cc6.alpic.live/mcp`
- Add to access token: enabled

This works around Keycloak's current lack of RFC 8707 `resource` parameter processing. When ChatGPT asks for one of the MCP scopes, Keycloak adds the exact MCP resource URL to the access token's `aud` claim, and KasbifyDev validates it.

## 3. Ensure identity claims are available

The authorization request must be able to request:

- `openid`
- `profile`
- `email`

The access token used by KasbifyDev must contain the configured email claim (`email` by default). Shared mode uses it for audit/policy information. Registry mode additionally maps the verified email to exactly one active `users.db` user.

## 4. Client registration

### DCR path — works with the current Keycloak deployment

FastMCP 3.4.7's `KeycloakAuthProvider` supports Keycloak Dynamic Client Registration. Keep Keycloak's OpenID client-registration endpoint available and configure the anonymous client-registration policies so OpenAI may register a public OAuth client with the allowed MCP/OpenID scopes.

Check the realm discovery document and ensure it publishes a `registration_endpoint` and `S256` PKCE support.

### CIMD path — preferred future option

Current OpenAI clients prefer Client ID Metadata Documents when the authorization server supports them. Keycloak supports CIMD behind its experimental `cimd` feature. This is not required for KasbifyDev v0.1 because DCR remains supported, but it is the preferred follow-up once the existing flow is stable.

If enabling CIMD later, configure Keycloak Client Policies to trust ChatGPT's HTTPS client metadata document domain and keep the redirect/issuer rules aligned with OpenAI's current OAuth documentation.

## 5. Alpic environment

Enable OAuth on the Alpic deployment with:

```env
MCP_AUTH_MODE=oidc
MCP_OIDC_IDENTITY_MODE=shared
MCP_OIDC_ISSUER=https://auth.dev.yektaertebat.ir/realms/engineering
MCP_OIDC_REQUIRED_REALM_ROLE=kasbifydev
MCP_OIDC_SHARED_ROLE=readonly
MCP_OIDC_SCOPES=openid,profile,email,mcp:tools,mcp:resources,mcp:prompts
```

Alpic supplies `ALPIC_HOST`, so `MCP_PUBLIC_URL` is optional there. KasbifyDev derives the audience as `${ALPIC_HOST}/mcp`. You may pin it explicitly:

```env
MCP_OIDC_AUDIENCE=https://odoo-mcp-19-cff81cc6.alpic.live/mcp
```

Keep the existing `MCP_API_KEY` during migration if older MCP clients still need it. OAuth metadata is served by the Keycloak provider while `MultiAuth` continues accepting the legacy token.

## 6. Enable writes only after read-only OAuth works

Start with:

```env
MCP_OIDC_SHARED_ROLE=readonly
```

After OAuth, audience, and role gating are verified end to end, change to:

```env
MCP_OIDC_SHARED_ROLE=support
```

This enables write-capable MCP calls for the shared Odoo service identity. It does **not** bypass KasbifyDev's safety classifier or confirmation-token flow.

For stronger attribution, deploy registry mode instead and store a separate Odoo credential for each user:

```env
MCP_OIDC_IDENTITY_MODE=registry
USERS_DB_PATH=/registry/users.db
```

## 7. Validate before connecting ChatGPT

Run:

```bash
python plugins/kasbifydev/scripts/check_oauth.py \
  --mcp-origin https://odoo-mcp-19-cff81cc6.alpic.live \
  --issuer https://auth.dev.yektaertebat.ir/realms/engineering
```

The checker validates the protected-resource document, issuer discovery, PKCE support, client-registration capability, scopes, and canonical resource URL.

## References

- OpenAI Plugins authentication: `https://developers.openai.com/plugins/build/auth`
- Keycloak MCP authorization: `https://www.keycloak.org/securing-apps/mcp-authz-server`
- Alpic OAuth setup: `https://docs.alpic.ai/secure/auth/oauth-setup`
