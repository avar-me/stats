from __future__ import annotations

from pathlib import Path

import yaml


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict):
        raise SystemExit(f"{path} must contain a sources mapping")
    return data
