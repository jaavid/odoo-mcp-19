#!/usr/bin/env python3
"""Bind a ChatGPT App ID into the KasbifyDev plugin package."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
APP_BINDING = ROOT / ".app.json"


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise SystemExit("usage: bind_app.py <chatgpt-app-id>")

    app_id = sys.argv[1].strip()
    payload = {
        "apps": {
            "kasbifydev": {
                "id": app_id,
                "required": True,
            }
        }
    }
    APP_BINDING.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Bound KasbifyDev to ChatGPT app: {app_id}")


if __name__ == "__main__":
    main()
