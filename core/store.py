"""Per-source history files. A failed source never rewrites another source's file."""

from __future__ import annotations

import json
from pathlib import Path

from core.model import Observation


def empty_meta() -> dict:
    return {
        "state": "new",
        "last_success": None,
        "last_attempt": None,
        "last_error": None,
        "last_records": 0,
        "entity_errors": {},
        "entity_info": {},
        "warnings": [],
    }


class HistoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / "data" / "history"
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, source: str) -> Path:
        if "/" in source or ".." in source or not source:
            raise ValueError(f"unsafe source id {source!r}")
        return self.directory / f"{source}.json"

    def load(self, source: str) -> dict:
        path = self.path_for(source)
        if not path.exists():
            return {"meta": empty_meta(), "observations": {}}
        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
        raw.setdefault("meta", empty_meta())
        raw.setdefault("observations", {})
        return raw

    def save(self, source: str, document: dict) -> None:
        path = self.path_for(source)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def observations(self, source: str) -> list[dict]:
        return list(self.load(source)["observations"].values())

    def merge(self, source: str, observations: list[Observation]) -> int:
        document = self.load(source)
        stored: dict = document["observations"]
        written = 0
        for observation in observations:
            if observation.source != source:
                raise ValueError(f"{observation.source} wrote into {source}")
            incoming = observation.to_dict()
            current = stored.get(observation.key)
            if current is not None and not _should_replace(current, incoming):
                continue
            stored[observation.key] = incoming
            written += 1
        document["observations"] = stored
        self.save(source, document)
        return written

    def record_run(
        self,
        source: str,
        *,
        state: str,
        attempted_at: str,
        records: int,
        error: str | None = None,
        entity_errors: dict | None = None,
        entity_info: dict | None = None,
        warnings: list[str] | None = None,
        success: bool = False,
    ) -> None:
        document = self.load(source)
        meta = document["meta"]
        meta["state"] = state
        meta["last_attempt"] = attempted_at
        meta["last_records"] = records
        meta["last_error"] = error
        meta["entity_errors"] = entity_errors or {}
        if entity_info:
            meta["entity_info"] = {**meta.get("entity_info", {}), **entity_info}
        meta["warnings"] = warnings or []
        if success:
            meta["last_success"] = attempted_at
            meta["last_error"] = None
        document["meta"] = meta
        self.save(source, document)


def _should_replace(current: dict, incoming: dict) -> bool:
    """A later revision may correct a value. An empty reading must not erase a real one."""
    if incoming.get("value") is None and current.get("value") is not None:
        return False
    if incoming.get("status") == "unavailable" and current.get("status") != "unavailable":
        return False
    return str(incoming.get("revision") or "") >= str(current.get("revision") or "")
