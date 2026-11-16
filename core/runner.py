"""Run source modules independently and publish whatever succeeded."""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from collectors.base import Context, SourceError, SourceNotConfigured
from collectors.registry import SOURCES
from core.aggregate import build_public
from core.config import load_config
from core.model import stamp
from core.privacy import assert_public_safe, scrub
from core.redact import redact
from core.store import HistoryStore


@dataclass
class RunReport:
    source: str
    status: str
    records: int
    message: str


def run_sources(config: dict, *, root: Path, env: dict | None = None, client=None, now: datetime | None = None, sources=None) -> list[RunReport]:
    moment = now or datetime.now().astimezone()
    environment = dict(os.environ if env is None else env)
    store = HistoryStore(root)
    http = client
    if http is None:
        from core.http import UrllibClient
        http = UrllibClient()
    reports: list[RunReport] = []
    for source in sources or [item() for item in SOURCES]:
        reports.append(_run_one(source, config, store, environment, http, root, moment))
    return reports


def _run_one(source, config, store, env, client, root, moment: datetime) -> RunReport:
    block = config.get("sources", {}).get(source.id)
    attempted = stamp(moment)
    if block is None:
        store.record_run(source.id, state="error", attempted_at=attempted, records=0, error="Нет блока sources." + source.id)
        return RunReport(source.id, "error", 0, "Нет блока конфигурации")
    if not block.get("enabled", False):
        store.record_run(
            source.id,
            state="disabled",
            attempted_at=attempted,
            records=0,
            error=None,
        )
        return RunReport(source.id, "disabled", 0, "выключен")
    ctx = Context(config=block, env=env, now=moment, client=client, root=root)
    try:
        result = source.collect(ctx)
    except SourceNotConfigured as error:
        message = redact(str(error))
        store.record_run(source.id, state="not_configured", attempted_at=attempted, records=0, error=message)
        return RunReport(source.id, "not_configured", 0, message)
    except SourceError as error:
        message = redact(str(error))
        store.record_run(source.id, state="error", attempted_at=attempted, records=0, error=message)
        return RunReport(source.id, "error", 0, message)
    except Exception as error:
        message = redact(f"{type(error).__name__}: {error}")
        traceback.print_exc()
        store.record_run(source.id, state="error", attempted_at=attempted, records=0, error=message)
        return RunReport(source.id, "error", 0, message)
    written = store.merge(source.id, result.observations)
    warnings = [redact(item) for item in result.warnings]
    entity_errors = {key: redact(value) for key, value in result.entity_errors.items()}
    store.record_run(
        source.id,
        state="ok",
        attempted_at=attempted,
        records=written,
        entity_errors=entity_errors,
        entity_info=result.entity_info,
        warnings=warnings,
        success=True,
    )
    message = "; ".join(warnings + [f"{key}: {value}" for key, value in entity_errors.items()])
    return RunReport(source.id, "ok", written, message)


def publish(config: dict, *, root: Path, now: datetime | None = None, sources=None) -> tuple[dict, dict]:
    moment = now or datetime.now().astimezone()
    store = HistoryStore(root)
    active = sources or [item() for item in SOURCES]
    summary, history = build_public(store, config, active, moment)
    summary = scrub(summary)
    history = scrub(history)
    assert_public_safe(summary)
    assert_public_safe(history)
    destination = root / "data" / "public"
    destination.mkdir(parents=True, exist_ok=True)
    _write(destination / "summary.json", summary)
    _write(destination / "history.json", history)
    site_data = root / "site" / "data"
    site_data.mkdir(parents=True, exist_ok=True)
    _write(site_data / "summary.json", summary)
    _write(site_data / "history.json", history)
    return summary, history


def _write(path: Path, payload: dict) -> None:
    import json
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Collect enabled sources and publish the dashboard JSON")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    config = load_config(root / args.config if not Path(args.config).is_absolute() else Path(args.config))
    reports = run_sources(config, root=root)
    publish(config, root=root)
    failed = False
    for report in reports:
        print(f"{report.source}: {report.status} records={report.records} {report.message}".rstrip())
        if report.status == "error":
            failed = True
    return 1 if failed else 0
