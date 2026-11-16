"""Interface shared by every data source. Modules do not call each other."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


class SourceNotConfigured(Exception):
    """Credentials or required settings are absent. History stays as it is."""


class SourceError(Exception):
    """The source was configured but this run failed. Other sources still run."""


@dataclass(frozen=True)
class Entity:
    id: str
    title: str
    link: str = ""


@dataclass
class Context:
    config: dict
    env: dict
    now: datetime
    client: object
    root: Path


@dataclass
class CollectResult:
    observations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    entity_errors: dict = field(default_factory=dict)
    entity_info: dict = field(default_factory=dict)


class Source:
    id: str
    title: str
    hint: str = ""

    def entities(self, block: dict) -> list[Entity]:
        return []

    def collect(self, ctx: Context) -> CollectResult:
        raise NotImplementedError
