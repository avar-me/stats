"""Small HTTP client. Tests pass a fake; collectors never open the network themselves."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from core.redact import redact, safe_url

MAX_BYTES = 20 * 1024 * 1024


class HttpError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass
class HttpResponse:
    status: int
    body: bytes

    def json(self) -> object:
        return json.loads(self.body.decode("utf-8"))

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding)


class UrllibClient:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int = 30,
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(MAX_BYTES + 1)
                status = response.status
        except urllib.error.HTTPError as error:
            payload = error.read(4000)
            detail = redact(payload.decode("utf-8", errors="replace"))[:400]
            raise HttpError(f"{method} {safe_url(url)} -> {error.code}: {detail}", error.code) from None
        except urllib.error.URLError as error:
            raise HttpError(f"{method} {safe_url(url)} failed: {redact(str(error.reason))}") from None
        if len(payload) > MAX_BYTES:
            raise HttpError(f"{method} {safe_url(url)} exceeded {MAX_BYTES} bytes")
        if status >= 400:
            detail = redact(payload.decode("utf-8", errors="replace"))[:400]
            raise HttpError(f"{method} {safe_url(url)} -> {status}: {detail}", status)
        return HttpResponse(status, payload)


class FakeClient:
    """Route table of (method, url substring, status, body). Body may be bytes or JSON-able."""

    def __init__(self, routes: list[tuple]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int = 30,
    ) -> HttpResponse:
        del headers, timeout
        self.calls.append((method, url, body))
        for route_method, part, status, payload in self.routes:
            matched = part(url) if callable(part) else part in url
            if method == route_method and matched:
                produced = payload(url) if callable(payload) else payload
                raw = produced if isinstance(produced, bytes) else json.dumps(produced).encode()
                if status >= 400:
                    raise HttpError(f"{method} {safe_url(url)} -> {status}", status)
                return HttpResponse(status, raw)
        raise HttpError(f"no fake route for {method} {safe_url(url)}")
