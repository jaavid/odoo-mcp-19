#!/usr/bin/env python3
"""Minimal structural validator for the KasbifyDev ChatGPT plugin package."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
APP_BINDING = ROOT / ".app.json"
SKILLS = ROOT / "skills"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")


def main() -> None:
    manifest = load_json(MANIFEST)
    binding = load_json(APP_BINDING)

    if manifest.get("name") != "kasbifydev":
        fail("plugin name must be 'kasbifydev'")

    if manifest.get("skills") != "./skills/":
        fail("plugin manifest must expose ./skills/")

    if manifest.get("apps") != "./.app.json":
        fail("plugin manifest must reference ./.app.json")

    app = binding.get("apps", {}).get("kasbifydev")
    if not isinstance(app, dict):
        fail(".app.json must define apps.kasbifydev")

    app_id = app.get("id")
    if not isinstance(app_id, str) or not app_id.strip():
        fail("apps.kasbifydev.id must be a non-empty string")

    skills = list(SKILLS.glob("*/SKILL.md"))
    if not skills:
        fail("at least one skill must exist under skills/*/SKILL.md")

    placeholder = app_id == "REPLACE_WITH_CHATGPT_APP_ID"
    state = "READY_FOR_APP_BINDING" if placeholder else "READY"
    print(f"KasbifyDev plugin validation: {state}")
    print(f"skills: {len(skills)}")
    print(f"app id: {app_id}")


if __name__ == "__main__":
    main()
