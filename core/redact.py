"""Strip credentials from messages that can reach logs or the public site."""

from __future__ import annotations

import re

_PATTERNS = (
    re.compile(r"\d{6,12}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"bot\d{6,12}:[A-Za-z0-9_-]{20,}", re.IGNORECASE),
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"ya29\.[0-9A-Za-z._\-]+"),
    re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]+?-----END [A-Z0-9 ]+-----"),
    re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"),
)


def redact(text: str) -> str:
    cleaned = str(text)
    for pattern in _PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    cleaned = re.sub(r"/bot\[redacted\]", "/bot[redacted]", cleaned)
    return cleaned


def safe_url(url: str) -> str:
    return redact(re.sub(r"/bot\d{6,}:[^/\s]+", "/bot[redacted]", url))
