#!/usr/bin/env python3
"""Fail if the files about to be deployed are demo data or contain a secret."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.privacy import assert_public_safe


def main() -> int:
    for name in ("summary.json", "history.json"):
        path = ROOT / "data" / "public" / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("preview"):
            print(f"{path} содержит демонстрационные данные")
            return 1
        assert_public_safe(payload)
    print("public json ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
