"""Administrative CLI for the multi-user MCP registry.

The MCP server opens ``users.db`` read-only. This module is the supported
writer for creating the schema, users, per-user MCP bearer keys, encrypted
Odoo credentials, and optional prompt/skill allowlists.

Typical container usage:

    python -m odoo_mcp.registry_admin init
    python -m odoo_mcp.registry_admin user-add \
        --name "Jane Doe" --email jane@example.com \
        --role user --odoo-username jane@example.com

MCP keys are stored only as SHA-256 hashes. Odoo API keys are encrypted with
the same Fernet/PBKDF2 contract used by the runtime decryptor.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import os
import secrets
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .token_crypto import encrypt_secret, ensure_salt

ROLES = ("admin", "user", "readonly")
SERVER_NAME = "odoo"
MCP_KEY_PREFIX = "cv_odoo_"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    role TEXT NOT NULL DEFAULT 'user'
        CHECK (role IN ('admin', 'user', 'readonly')),
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    server TEXT NOT NULL DEFAULT 'odoo',
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_api_keys_lookup
    ON api_keys(server, key_hash, revoked_at);

CREATE TABLE IF NOT EXISTS user_odoo_credentials (
    user_id TEXT PRIMARY KEY,
    odoo_username TEXT NOT NULL,
    encrypted_secret TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_skills (
    user_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    PRIMARY KEY (user_id, skill_name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_path(value: str | None = None) -> Path:
    if value:
        return Path(value)
    return Path(os.environ.get("USERS_DB_PATH", "./data/users.db"))


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_salt(path)
    with _connect(path) as conn:
        conn.executescript(SCHEMA)

    # The runtime container only needs read access; these are not secrets.
    try:
        path.chmod(0o644)
        (path.parent / ".token_salt").chmod(0o644)
    except OSError:
        pass


def _require_role(role: str) -> str:
    role = role.strip().lower()
    if role not in ROLES:
        raise ValueError(f"invalid role '{role}'; expected one of: {', '.join(ROLES)}")
    return role


def _normalize_email(email: str) -> str:
    email = email.strip()
    if not email or "@" not in email:
        raise ValueError(f"invalid email: {email!r}")
    return email


def _user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
        (email,),
    ).fetchone()


def _create_user(
    conn: sqlite3.Connection,
    *,
    name: str,
    email: str,
    role: str,
) -> str:
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    email = _normalize_email(email)
    role = _require_role(role)

    if _user_by_email(conn, email) is not None:
        raise ValueError(f"user already exists: {email}")

    user_id = f"usr_{uuid.uuid4().hex}"
    now = _utcnow()
    conn.execute(
        """
        INSERT INTO users(id, name, email, role, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """,
        (user_id, name, email, role, now, now),
    )
    return user_id


def _create_mcp_key(conn: sqlite3.Connection, user_id: str) -> str:
    token = MCP_KEY_PREFIX + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    key_id = f"key_{uuid.uuid4().hex}"
    conn.execute(
        """
        INSERT INTO api_keys(id, user_id, server, key_hash, key_prefix, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (key_id, user_id, SERVER_NAME, key_hash, token[:16], _utcnow()),
    )
    return token


def _set_odoo_credentials(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
    user_id: str,
    username: str,
    api_key: str,
) -> None:
    username = username.strip()
    api_key = api_key.strip()
    if not username:
        raise ValueError("Odoo username is required")
    if not api_key:
        raise ValueError("Odoo API key is required")

    now = _utcnow()
    encrypted = encrypt_secret({"api_key": api_key}, db_path=db_path)
    conn.execute(
        """
        INSERT INTO user_odoo_credentials(user_id, odoo_username, encrypted_secret, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            odoo_username = excluded.odoo_username,
            encrypted_secret = excluded.encrypted_secret,
            updated_at = excluded.updated_at
        """,
        (user_id, username, encrypted, now),
    )


def _replace_skills(conn: sqlite3.Connection, user_id: str, skills: Iterable[str]) -> None:
    normalized = sorted({skill.strip() for skill in skills if skill.strip()})
    conn.execute("DELETE FROM user_skills WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO user_skills(user_id, skill_name) VALUES (?, ?)",
        [(user_id, skill) for skill in normalized],
    )


def _get_user_or_fail(conn: sqlite3.Connection, email: str) -> sqlite3.Row:
    row = _user_by_email(conn, _normalize_email(email))
    if row is None:
        raise ValueError(f"user not found: {email}")
    return row


def cmd_init(args: argparse.Namespace) -> int:
    path = _db_path(args.db)
    _initialize(path)
    print(f"Registry initialized: {path}")
    print(f"Salt: {path.parent / '.token_salt'}")
    return 0


def cmd_user_add(args: argparse.Namespace) -> int:
    path = _db_path(args.db)
    _initialize(path)

    odoo_api_key: str | None = None
    if args.odoo_username:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "--odoo-username requires an interactive terminal so the API key can be "
                "entered securely. Use import-csv for non-interactive bulk creation."
            )
        odoo_api_key = getpass.getpass("Odoo API key: ").strip()
        if not odoo_api_key:
            raise ValueError("Odoo API key cannot be empty")

    with _connect(path) as conn:
        user_id = _create_user(
            conn,
            name=args.name,
            email=args.email,
            role=args.role,
        )
        token = _create_mcp_key(conn, user_id)
        if args.odoo_username and odoo_api_key:
            _set_odoo_credentials(
                conn,
                db_path=path,
                user_id=user_id,
                username=args.odoo_username,
                api_key=odoo_api_key,
            )
        _replace_skills(conn, user_id, args.skill or [])

    print(f"Created user: {args.email}")
    print("MCP key (shown once):")
    print(token)
    return 0


def cmd_key_create(args: argparse.Namespace) -> int:
    path = _db_path(args.db)
    _initialize(path)

    with _connect(path) as conn:
        user = _get_user_or_fail(conn, args.email)
        if args.revoke_existing:
            conn.execute(
                """
                UPDATE api_keys
                   SET revoked_at = ?
                 WHERE user_id = ? AND server = ? AND revoked_at IS NULL
                """,
                (_utcnow(), user["id"], SERVER_NAME),
            )
        token = _create_mcp_key(conn, user["id"])

    print(f"Created MCP key for: {args.email}")
    print("MCP key (shown once):")
    print(token)
    return 0


def cmd_keys_revoke(args: argparse.Namespace) -> int:
    path = _db_path(args.db)
    _initialize(path)

    with _connect(path) as conn:
        user = _get_user_or_fail(conn, args.email)
        cur = conn.execute(
            """
            UPDATE api_keys
               SET revoked_at = ?
             WHERE user_id = ? AND server = ? AND revoked_at IS NULL
            """,
            (_utcnow(), user["id"], SERVER_NAME),
        )

    print(f"Revoked {cur.rowcount} active MCP key(s) for: {args.email}")
    return 0


def cmd_odoo_set(args: argparse.Namespace) -> int:
    path = _db_path(args.db)
    _initialize(path)

    if not sys.stdin.isatty():
        raise RuntimeError("odoo-set must run interactively so the API key is not exposed in argv")
    api_key = getpass.getpass("Odoo API key: ").strip()
    if not api_key:
        raise ValueError("Odoo API key cannot be empty")

    with _connect(path) as conn:
        user = _get_user_or_fail(conn, args.email)
        _set_odoo_credentials(
            conn,
            db_path=path,
            user_id=user["id"],
            username=args.username,
            api_key=api_key,
        )

    print(f"Odoo credentials updated for: {args.email}")
    return 0


def cmd_user_disable(args: argparse.Namespace) -> int:
    path = _db_path(args.db)
    _initialize(path)

    with _connect(path) as conn:
        user = _get_user_or_fail(conn, args.email)
        now = _utcnow()
        conn.execute(
            "UPDATE users SET is_active = 0, updated_at = ? WHERE id = ?",
            (now, user["id"]),
        )
        conn.execute(
            """
            UPDATE api_keys
               SET revoked_at = COALESCE(revoked_at, ?)
             WHERE user_id = ? AND server = ?
            """,
            (now, user["id"], SERVER_NAME),
        )

    print(f"Disabled user and revoked active keys: {args.email}")
    return 0


def cmd_list_users(args: argparse.Namespace) -> int:
    path = _db_path(args.db)
    _initialize(path)

    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT
                u.name,
                u.email,
                u.role,
                u.is_active,
                CASE WHEN c.user_id IS NULL THEN 0 ELSE 1 END AS has_odoo,
                SUM(CASE WHEN k.id IS NOT NULL AND k.revoked_at IS NULL THEN 1 ELSE 0 END) AS active_keys
            FROM users u
            LEFT JOIN user_odoo_credentials c ON c.user_id = u.id
            LEFT JOIN api_keys k ON k.user_id = u.id AND k.server = ?
            GROUP BY u.id
            ORDER BY u.name COLLATE NOCASE, u.email COLLATE NOCASE
            """,
            (SERVER_NAME,),
        ).fetchall()

    if not rows:
        print("No users.")
        return 0

    headers = ("NAME", "EMAIL", "ROLE", "ACTIVE", "ODOO", "KEYS")
    data = [
        (
            row["name"],
            row["email"],
            row["role"],
            "yes" if row["is_active"] else "no",
            "yes" if row["has_odoo"] else "no",
            str(row["active_keys"] or 0),
        )
        for row in rows
    ]
    widths = [
        max(len(headers[i]), *(len(str(row[i])) for row in data))
        for i in range(len(headers))
    ]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in data:
        print("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))
    return 0


def _open_csv_input(filename: str):
    if filename == "-":
        return sys.stdin, False
    return Path(filename).open("r", encoding="utf-8-sig", newline=""), True


def cmd_import_csv(args: argparse.Namespace) -> int:
    path = _db_path(args.db)
    _initialize(path)

    output = Path(args.output)
    if output.exists() and not args.force:
        raise FileExistsError(f"output already exists: {output}; use --force to replace it")

    stream, should_close = _open_csv_input(args.file)
    generated: list[dict[str, str]] = []
    try:
        reader = csv.DictReader(stream)
        required = {"name", "email"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required column(s): {', '.join(sorted(missing))}")

        with _connect(path) as conn:
            for line_no, row in enumerate(reader, start=2):
                name = (row.get("name") or "").strip()
                email = (row.get("email") or "").strip()
                role = (row.get("role") or "user").strip() or "user"
                odoo_username = (row.get("odoo_username") or "").strip()
                odoo_api_key = (row.get("odoo_api_key") or "").strip()
                skills = [
                    value.strip()
                    for value in (row.get("skills") or "").split(";")
                    if value.strip()
                ]

                if bool(odoo_username) != bool(odoo_api_key):
                    raise ValueError(
                        f"line {line_no}: odoo_username and odoo_api_key must either both be set or both be empty"
                    )

                try:
                    user_id = _create_user(conn, name=name, email=email, role=role)
                except Exception as exc:
                    raise ValueError(f"line {line_no}: {exc}") from exc

                token = _create_mcp_key(conn, user_id)
                if odoo_username:
                    _set_odoo_credentials(
                        conn,
                        db_path=path,
                        user_id=user_id,
                        username=odoo_username,
                        api_key=odoo_api_key,
                    )
                _replace_skills(conn, user_id, skills)
                generated.append({"name": name, "email": email, "mcp_key": token})
    finally:
        if should_close:
            stream.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "email", "mcp_key"])
        writer.writeheader()
        writer.writerows(generated)
    try:
        output.chmod(0o600)
    except OSError:
        pass

    print(f"Imported {len(generated)} user(s).")
    print(f"Generated MCP keys written to: {output}")
    print("The output contains plaintext secrets. Distribute them securely, then remove the file.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the Odoo MCP multi-user registry")
    parser.add_argument(
        "--db",
        help="Registry database path (default: USERS_DB_PATH or ./data/users.db)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Create the registry schema and salt")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("user-add", help="Create one user and generate an MCP key")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--role", choices=ROLES, default="user")
    p.add_argument("--odoo-username")
    p.add_argument("--skill", action="append", default=[])
    p.set_defaults(func=cmd_user_add)

    p = sub.add_parser("key-create", help="Generate another MCP key for an existing user")
    p.add_argument("--email", required=True)
    p.add_argument("--revoke-existing", action="store_true")
    p.set_defaults(func=cmd_key_create)

    p = sub.add_parser("keys-revoke", help="Revoke all active MCP keys for a user")
    p.add_argument("--email", required=True)
    p.set_defaults(func=cmd_keys_revoke)

    p = sub.add_parser("odoo-set", help="Set or rotate a user's Odoo API key")
    p.add_argument("--email", required=True)
    p.add_argument("--username", required=True)
    p.set_defaults(func=cmd_odoo_set)

    p = sub.add_parser("user-disable", help="Disable a user and revoke active MCP keys")
    p.add_argument("--email", required=True)
    p.set_defaults(func=cmd_user_disable)

    p = sub.add_parser("list-users", help="List users without displaying secrets")
    p.set_defaults(func=cmd_list_users)

    p = sub.add_parser("import-csv", help="Bulk-create users and generate one MCP key per user")
    p.add_argument("--file", default="-", help="Input CSV path, or '-' for stdin")
    p.add_argument(
        "--output",
        default="./generated-mcp-keys.csv",
        help="Output CSV for generated plaintext MCP keys",
    )
    p.add_argument("--force", action="store_true", help="Replace an existing output file")
    p.set_defaults(func=cmd_import_csv)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, RuntimeError, FileExistsError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
