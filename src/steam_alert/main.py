"""Ponto de entrada: consulta a Steam, decide e notifica."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .alert_manager import AlertStore, AlertStoreError
from .deal_detector import evaluate
from .discord_client import DiscordError, send_alert
from .logger import setup_logging
from .steam_client import SteamError, fetch_deal

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAMES = ROOT / "config" / "games.json"
DEFAULT_ALERTS = ROOT / "data" / "alerts.json"

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """games.json inválido."""


@dataclass(frozen=True)
class Game:
    name: str
    appid: int
    min_discount: int
    enabled: bool = True


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_games(path: Path) -> list[Game]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{path} não encontrado") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} não é um JSON válido") from exc
    if not isinstance(raw, list):
        raise ConfigError("games.json deve ser uma lista")

    games: list[Game] = []
    seen: set[int] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"item {index}: deve ser um objeto")
        name, appid = item.get("name"), item.get("appid")
        min_discount, enabled = item.get("min_discount"), item.get("enabled", True)
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"item {index}: 'name' inválido")
        if not _is_int(appid) or appid <= 0:
            raise ConfigError(f"item {index}: 'appid' deve ser inteiro positivo")
        if not _is_int(min_discount) or not 0 <= min_discount <= 100:
            raise ConfigError(f"item {index}: 'min_discount' deve estar entre 0 e 100")
        if not isinstance(enabled, bool):
            raise ConfigError(f"item {index}: 'enabled' deve ser true ou false")
        if appid in seen:
            raise ConfigError(f"item {index}: appid {appid} duplicado")
        seen.add(appid)
        games.append(Game(name.strip(), appid, min_discount, enabled))
    return games


def _valid_webhook(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (
        host in ("discord.com", "discordapp.com")
        or host.endswith((".discord.com", ".discordapp.com"))
    )


def run(games_path: Path, alerts_path: Path, webhook_url: str | None, *,
        dry_run: bool = False, fetch: Callable[..., Any] = fetch_deal,
        send: Callable[..., None] = send_alert,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep, request_delay: float = 1.0,
        session: Any = None) -> int:
    if not dry_run and not (webhook_url and _valid_webhook(webhook_url)):
        logger.error("DISCORD_WEBHOOK_URL ausente ou inválida")
        return 2

    games = [g for g in load_games(games_path) if g.enabled]
    store = AlertStore(alerts_path)
    store.load()
    session = session or requests.Session()
    now = now_fn()
    fetch_failures = send_failures = 0

    for index, game in enumerate(games):
        if index:
            sleep(request_delay)
        try:
            deal = fetch(game.appid, game.name, session=session)
        except SteamError as exc:
            logger.warning("%s", exc)
            fetch_failures += 1
            continue

        decision = evaluate(deal, game.min_discount, store.get(game.appid), now)
        logger.info("%s (%s): %d%% -> %s", deal.name, game.appid,
                    deal.discount_percent, decision.action.value)
        if dry_run:
            continue

        if decision.should_notify:
            try:
                send(webhook_url, deal, now, decision.previous_discount, session=session)
            except DiscordError as exc:
                logger.error("Alerta de %s não enviado: %s", deal.name, exc)
                send_failures += 1
                continue
        store.apply(deal, decision, now)

    if not dry_run:
        store.save()
    if send_failures or (games and fetch_failures == len(games)):
        return 1
    return 0


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Steam Deal Alert")
    parser.add_argument("--games", type=Path, default=DEFAULT_GAMES)
    parser.add_argument("--alerts", type=Path, default=DEFAULT_ALERTS)
    parser.add_argument("--dry-run", action="store_true",
                        help="consulta e decide, sem enviar nem gravar nada")
    args = parser.parse_args(argv)

    setup_logging()
    _load_dotenv(ROOT / ".env")
    try:
        return run(args.games, args.alerts, os.getenv("DISCORD_WEBHOOK_URL"),
                   dry_run=args.dry_run)
    except (ConfigError, AlertStoreError) as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
