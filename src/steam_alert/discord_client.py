"""Envio de alertas ao Discord via webhook."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from .steam_client import Deal

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3), "BRT")


class DiscordError(Exception):
    """Falha ao enviar mensagem ao Discord."""


def format_price(cents: int, currency: str = "BRL") -> str:
    units, rest = divmod(cents, 100)
    value = f"{units:,}".replace(",", ".") + f",{rest:02d}"
    return f"R$ {value}" if currency == "BRL" else f"{currency} {value}"


def _color(discount: int) -> int:
    if discount >= 75:
        return 0xE74C3C
    if discount >= 50:
        return 0xE67E22
    if discount >= 25:
        return 0x2ECC71
    return 0x3498DB


def build_embed(deal: Deal, now: datetime, previous_discount: int | None = None) -> dict:
    cur = deal.currency
    description = (
        f"~~{format_price(deal.initial_price, cur)}~~\n"
        f"**{format_price(deal.final_price, cur)}**\n\n"
        f"🔥 **{deal.discount_percent}% OFF**\n\n"
        f"Você economiza **{format_price(deal.savings, cur)}**!"
    )
    fields = []
    if previous_discount is not None and previous_discount != deal.discount_percent:
        fields.append({
            "name": "Desconto anterior",
            "value": f"{previous_discount}% → {deal.discount_percent}%",
            "inline": True,
        })
    fields.append({
        "name": "\u200b",
        "value": f"[🛒 Ver promoção na Steam]({deal.url})",
        "inline": False,
    })
    embed: dict[str, Any] = {
        "author": {"name": "🎮 Promoção na Steam 🎮"},
        "title": deal.name,
        "url": deal.url,
        "description": description,
        "color": _color(deal.discount_percent),
        "fields": fields,
        "footer": {"text": f"Detectado em {now.astimezone(BRT):%d/%m/%Y %H:%M} (Brasília)"},
        "timestamp": now.astimezone(timezone.utc).isoformat(),
    }
    if deal.image_url:
        embed["image"] = {"url": deal.image_url}
    return embed


def _retry_after(response: Any) -> float:
    value: Any = None
    try:
        value = response.json().get("retry_after")
    except (ValueError, AttributeError):
        pass
    if value is None:
        value = getattr(response, "headers", {}).get("Retry-After")
    try:
        return min(max(float(value), 1.0), 60.0)
    except (TypeError, ValueError):
        return 5.0


def send_alert(webhook_url: str, deal: Deal, now: datetime,
               previous_discount: int | None = None, *, session: Any = None,
               timeout: float = 10.0, max_retries: int = 3,
               sleep: Callable[[float], None] = time.sleep) -> None:
    payload = {
        "username": "Promoção na Steam",
        "embeds": [build_embed(deal, now, previous_discount)],
    }
    http = session or requests
    for attempt in range(1, max_retries + 1):
        try:
            response = http.post(webhook_url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            reason, wait = type(exc).__name__, 2.0 * attempt
        else:
            status = response.status_code
            if status in (200, 204):
                return
            if status == 429:
                reason, wait = "HTTP 429", _retry_after(response)
            elif status >= 500:
                reason, wait = f"HTTP {status}", 2.0 * attempt
            else:
                raise DiscordError(f"Discord recusou a requisição (HTTP {status})")
        if attempt == max_retries:
            raise DiscordError(f"falha após {max_retries} tentativas ({reason})")
        logger.warning("Discord: tentativa %d falhou (%s); nova em %.1fs",
                       attempt, reason, wait)
        sleep(wait)
