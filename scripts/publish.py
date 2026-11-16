#!/usr/bin/env python3
"""Rebuild public JSON from history without contacting any provider."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import load_config
from core.runner import publish

if __name__ == "__main__":
    root = ROOT
    publish(load_config(root / "config.yaml"), root=root)
    print(f"wrote {root / 'data' / 'public'}")
