#!/usr/bin/env python3
"""Create one ONGOING App Store Connect analytics request. Requires an Admin key.

The daily collector never calls this. Apple allows the request to go idle if
reports are not downloaded, and creating duplicates returns 409.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collectors.apple import apple_token, create_ongoing_request
from core.config import load_config
from core.http import UrllibClient
from core.secrets import load_pem, required


def main(argv: list[str]) -> int:
    if "--confirm" not in argv:
        print("Команда создаёт ONGOING-запрос в App Store Connect.")
        print("Нужен ключ с ролью Admin. Повторите с --confirm, когда ключ уже в окружении.")
        return 1
    env = dict(**__import__("os").environ)
    secrets = required(env, "APPLE_KEY_ID", "APPLE_ISSUER_ID", "APPLE_PRIVATE_KEY")
    config = load_config(ROOT / "config.yaml")
    app_id = (env.get("APPLE_APP_ID") or config["sources"]["apple"].get("app_id") or "").strip()
    if not app_id:
        print("Нужен APPLE_APP_ID")
        return 1
    now = datetime.now(timezone.utc)
    token = apple_token(secrets["APPLE_KEY_ID"], secrets["APPLE_ISSUER_ID"], load_pem(secrets["APPLE_PRIVATE_KEY"]), now)
    request_id = create_ongoing_request(UrllibClient(), token, app_id)
    print(f"Запрос создан: {request_id}. Первые отчёты обычно появляются через 1–2 дня.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as error:
        from core.redact import redact
        print(redact(str(error)))
        raise SystemExit(1)
