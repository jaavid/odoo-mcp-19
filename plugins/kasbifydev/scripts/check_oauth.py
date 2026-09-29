#!/usr/bin/env python3
"""Validate MCP protected-resource and Keycloak OAuth discovery metadata."""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MCP_SCOPES = {"mcp:tools", "mcp:resources", "mcp:prompts"}


def fetch_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "kasbifydev-oauth-check/0.1",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"GET {url} did not return a JSON object")
    return payload


def find_resource_metadata(origin: str) -> tuple[str, dict]:
    candidates = [
        f"{origin}/.well-known/oauth-protected-resource/mcp",
        f"{origin}/.well-known/oauth-protected-resource",
    ]
    errors: list[str] = []
    for url in candidates:
        try:
            return url, fetch_json(url)
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError("Protected-resource metadata not found:\n  " + "\n  ".join(errors))


def check(args: argparse.Namespace) -> int:
    origin = args.mcp_origin.rstrip("/")
    issuer = args.issuer.rstrip("/")
    expected_resource = args.resource or f"{origin}/mcp"
    failures: list[str] = []

    try:
        resource_url, resource_meta = find_resource_metadata(origin)
        print(f"OK protected-resource metadata: {resource_url}")
    except RuntimeError as exc:
        print(f"FAIL {exc}")
        return 1

    actual_resource = resource_meta.get("resource")
    if actual_resource != expected_resource:
        failures.append(f"resource mismatch: expected {expected_resource!r}, got {actual_resource!r}")
    else:
        print(f"OK resource: {actual_resource}")

    authorization_servers = resource_meta.get("authorization_servers", [])
    if issuer not in authorization_servers:
        failures.append(f"issuer {issuer!r} missing from authorization_servers={authorization_servers!r}")
    else:
        print(f"OK authorization server: {issuer}")

    advertised_scopes = set(resource_meta.get("scopes_supported") or [])
    missing_resource_scopes = MCP_SCOPES - advertised_scopes
    if missing_resource_scopes:
        failures.append(
            "protected-resource metadata is missing MCP scopes: " + ", ".join(sorted(missing_resource_scopes))
        )
    else:
        print("OK protected-resource MCP scopes")

    discovery_url = f"{issuer}/.well-known/openid-configuration"
    try:
        oidc = fetch_json(discovery_url)
        print(f"OK OIDC discovery: {discovery_url}")
    except RuntimeError as exc:
        failures.append(str(exc))
        oidc = {}

    if oidc:
        if oidc.get("issuer") != issuer:
            failures.append(f"OIDC issuer mismatch: expected {issuer!r}, got {oidc.get('issuer')!r}")
        methods = set(oidc.get("code_challenge_methods_supported") or [])
        if "S256" not in methods:
            failures.append("OIDC metadata does not advertise PKCE S256")
        else:
            print("OK PKCE: S256")

        has_dcr = bool(oidc.get("registration_endpoint"))
        has_cimd = oidc.get("client_id_metadata_document_supported") is True
        if not (has_dcr or has_cimd):
            failures.append("OIDC metadata advertises neither DCR nor CIMD client registration")
        else:
            modes = [name for name, enabled in (("DCR", has_dcr), ("CIMD", has_cimd)) if enabled]
            print("OK client registration: " + " + ".join(modes))

        oidc_scopes = set(oidc.get("scopes_supported") or [])
        missing_oidc_scopes = MCP_SCOPES - oidc_scopes
        if missing_oidc_scopes:
            failures.append("Keycloak discovery is missing MCP scopes: " + ", ".join(sorted(missing_oidc_scopes)))
        else:
            print("OK Keycloak MCP scopes")

    if failures:
        print("\nOAuth validation FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nKasbifyDev OAuth discovery is ready for an MCP client.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mcp-origin",
        required=True,
        help="Public MCP origin without /mcp",
    )
    parser.add_argument(
        "--issuer",
        required=True,
        help="Exact Keycloak realm issuer",
    )
    parser.add_argument(
        "--resource",
        help="Expected protected resource URL; defaults to <mcp-origin>/mcp",
    )
    raise SystemExit(check(parser.parse_args()))


if __name__ == "__main__":
    main()
