# Multi-user deployment with GHCR

The default Docker image is:

```text
ghcr.io/jaavid/odoo-mcp-19:latest
```

Every push to `master` publishes `latest`, `master`, and a `sha-*` tag. Git tags
matching `v*` are published with the same tag. Images are built for
`linux/amd64` and `linux/arm64`.

## 1. Pull the image

If the GHCR package is public:

```bash
docker pull ghcr.io/jaavid/odoo-mcp-19:latest
```

If it is private, log in first with a GitHub token that has `read:packages`:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u jaavid --password-stdin
docker pull ghcr.io/jaavid/odoo-mcp-19:latest
```

## 2. Create deployment directories and the encryption secret

From the directory containing the compose files:

```bash
mkdir -p data secrets
openssl rand -base64 48 > secrets/token_encryption_key
chmod 600 secrets/token_encryption_key
```

Keep this file backed up securely. Losing or changing it makes stored Odoo API
keys undecryptable.

Create `.env`:

```dotenv
MCP_IMAGE=ghcr.io/jaavid/odoo-mcp-19:latest

ODOO_URL=https://dev.yekta.org
ODOO_DB=odoo_yekta

MCP_TRANSPORT=streamable-http
MCP_PORT=8080
MCP_BIND=127.0.0.1
MCP_SAFETY_MODE=strict

USERS_DB_HOST_DIR=./data
TOKEN_ENCRYPTION_KEY_SECRET=./secrets/token_encryption_key

# Recommended for true per-user attribution:
MCP_API_KEY=
```

## 3. Initialize the registry

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.multiuser.yml \
  run --rm registry-admin init
```

This creates:

```text
data/users.db
data/.token_salt
```

The schema contains:

- `users`
- `api_keys`
- `user_odoo_credentials`
- `user_skills`

MCP bearer tokens are stored only as SHA-256 hashes. Odoo API keys are stored
as Fernet-encrypted JSON using the secret above.

## 4. Add one user interactively

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.multiuser.yml \
  run --rm registry-admin \
  user-add \
  --name "Javid Momeni" \
  --email "javid@example.com" \
  --role admin \
  --odoo-username "javid@example.com"
```

The command prompts for the Odoo API key without echoing it, then prints a new
MCP key exactly once:

```text
cv_odoo_...
```

Give that MCP key only to that user. It is not recoverable from `users.db`
because only its SHA-256 hash is stored.

Roles:

- `admin`: read/write and unrestricted skill visibility.
- `user`: read/write using that user's Odoo permissions.
- `readonly`: MCP token receives read-only scopes.

## 5. Bulk-create users

Copy the example:

```bash
cp examples/users.example.csv users.csv
```

CSV columns:

```text
name,email,role,odoo_username,odoo_api_key,skills
```

`skills` is optional and uses `;` as the separator. Both Odoo fields may be
left empty and configured later.

Import it:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.multiuser.yml \
  run --rm -T registry-admin \
  import-csv \
  --file - \
  --output /registry/generated-mcp-keys.csv \
  < users.csv
```

The generated per-user MCP keys are written to:

```text
data/generated-mcp-keys.csv
```

That output file contains plaintext MCP secrets. Distribute the keys securely
and delete the file afterwards:

```bash
rm -f data/generated-mcp-keys.csv users.csv
```

Do not commit either file.

## 6. Useful registry commands

List users without exposing secrets:

```bash
docker compose -f docker-compose.yml -f docker-compose.multiuser.yml \
  run --rm registry-admin list-users
```

Rotate an MCP key and revoke all previous keys:

```bash
docker compose -f docker-compose.yml -f docker-compose.multiuser.yml \
  run --rm registry-admin key-create \
  --email javid@example.com \
  --revoke-existing
```

Rotate only the Odoo API key:

```bash
docker compose -f docker-compose.yml -f docker-compose.multiuser.yml \
  run --rm registry-admin odoo-set \
  --email javid@example.com \
  --username javid@example.com
```

Disable a user and revoke active MCP keys:

```bash
docker compose -f docker-compose.yml -f docker-compose.multiuser.yml \
  run --rm registry-admin user-disable \
  --email javid@example.com
```

## 7. Start or update the MCP server

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.multiuser.yml \
  pull

docker compose \
  -f docker-compose.yml \
  -f docker-compose.multiuser.yml \
  up -d odoo-mcp
```

For later deployments:

```bash
docker compose -f docker-compose.yml -f docker-compose.multiuser.yml pull
docker compose -f docker-compose.yml -f docker-compose.multiuser.yml up -d
```

The runtime service mounts `data/` read-only. Registry writes are only done by
the one-shot `registry-admin` service.
