"""Reject documents that would publish a credential."""

from __future__ import annotations

import json
import re

FORBIDDEN_KEYS = frozenset({
    "user_id",
    "userid",
    "username",
    "query",
    "text",
    "message",
    "ip",
    "phone",
    "hash",
    "user_hash",
    "token",
    "authorization",
    "private_key",
    "password",
    "secret",
})

_TOKEN = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{20,}")
_MARKERS = ("-----BEGIN ", "PRIVATE KEY", "ya29.", "Bearer ")


def scrub(value):
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if str(key).lower() not in FORBIDDEN_KEYS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def assert_public_safe(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for marker in _MARKERS:
        if marker in text:
            raise RuntimeError("Публичный JSON содержит секрет и не будет записан")
    if _TOKEN.search(text):
        raise RuntimeError("Публичный JSON содержит токен и не будет записан")
