"""Load secrets from the environment without printing them."""

from __future__ import annotations

import json
from pathlib import Path

from collectors.base import SourceNotConfigured


def required(env: dict, *names: str) -> dict[str, str]:
    found = {}
    missing = []
    for name in names:
        value = (env.get(name) or "").strip()
        if not value:
            missing.append(name)
        else:
            found[name] = value
    if missing:
        raise SourceNotConfigured("Не заданы секреты: " + ", ".join(missing))
    return found


def load_pem(value: str) -> str:
    if "BEGIN" in value:
        return value.replace("\\n", "\n")
    path = Path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    raise SourceNotConfigured("Приватный ключ не найден. Укажите PEM или путь к файлу вне репозитория.")


def load_service_account(value: str) -> dict:
    try:
        if value.strip().startswith("{"):
            data = json.loads(value)
        else:
            path = Path(value)
            if not path.is_file():
                raise SourceNotConfigured("GOOGLE_PLAY_CREDENTIALS должен быть JSON или путём к файлу JSON.")
            data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SourceNotConfigured("GOOGLE_PLAY_CREDENTIALS не является JSON.") from error
    if not data.get("client_email") or not data.get("private_key"):
        raise SourceNotConfigured("В ключе сервисного аккаунта нет client_email или private_key.")
    data["private_key"] = str(data["private_key"]).replace("\\n", "\n")
    return data
