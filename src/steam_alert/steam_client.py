"""Cliente da Steam Store API (appdetails)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

API_URL = "https://store.steampowered.com/api/appdetails"
STORE_URL = "https://store.steampowered.com/app/{appid}"
RETRY_STATUS = {429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)


class SteamError(Exception):
    """Falha ao consultar ou interpretar a resposta da Steam."""


class _Retryable(Exception):
    pass


@dataclass(frozen=True)
class Deal:
    appid: int
    name: str
    currency: str
    initial_price: int  # centavos
    final_price: int  # centavos
    discount_percent: int
    url: str
    image_url: str | None = None
    available: bool = True
    is_free: bool = False

    @property
    def savings(self) -> int:
        return max(self.initial_price - self.final_price, 0)


def _empty(appid: int, name: str, *, available: bool, is_free: bool = False,
           image: str | None = None) -> Deal:
    return Deal(
        appid=appid, name=name, currency="BRL", initial_price=0, final_price=0,
        discount_percent=0, url=STORE_URL.format(appid=appid), image_url=image,
        available=available, is_free=is_free,
    )


def parse_deal(appid: int, payload: Any, fallback_name: str) -> Deal:
    entry = payload.get(str(appid)) if isinstance(payload, dict) else None
    if not isinstance(entry, dict) or "success" not in entry:
        raise SteamError(f"appid {appid}: resposta inválida")
    if not entry["success"]:
        return _empty(appid, fallback_name, available=False)

    data = entry.get("data")
    if not isinstance(data, dict):
        raise SteamError(f"appid {appid}: resposta sem dados")

    name = data.get("name") or fallback_name
    image = data.get("header_image")
    if data.get("is_free"):
        return _empty(appid, name, available=True, is_free=True, image=image)

    price = data.get("price_overview")
    if not isinstance(price, dict):
        return _empty(appid, name, available=False, image=image)

    try:
        initial = price["initial"]
        final = price["final"]
        discount = price["discount_percent"]
        currency = price.get("currency", "BRL")
    except (KeyError, TypeError, ValueError) as exc:
        raise SteamError(f"appid {appid}: preço inválido") from exc
    if (any(isinstance(value, bool) or not isinstance(value, int)
            for value in (initial, final, discount))
            or not isinstance(currency, str)
            or len(currency.strip()) != 3
            or not currency.strip().isascii()
            or not currency.strip().isalpha()):
        raise SteamError(f"appid {appid}: preço inválido")
    if initial < 0 or final < 0 or not 0 <= discount <= 100:
        raise SteamError(f"appid {appid}: valores de preço fora do esperado")

    return Deal(
        appid=appid, name=name, currency=currency.strip().upper(),
        initial_price=initial, final_price=final, discount_percent=discount,
        url=STORE_URL.format(appid=appid), image_url=image,
    )


def _get_json(appid: int, session: Any, timeout: float, max_retries: int,
              backoff: float, sleep: Callable[[float], None]) -> Any:
    http = session or requests
    params = {"appids": appid, "cc": "br", "l": "brazilian"}
    last = "erro desconhecido"
    for attempt in range(1, max_retries + 1):
        try:
            response = http.get(API_URL, params=params, timeout=timeout)
            if response.status_code in RETRY_STATUS:
                raise _Retryable(f"HTTP {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError, _Retryable) as exc:
            last = f"{type(exc).__name__}: {exc}"
        except (requests.HTTPError, ValueError) as exc:
            raise SteamError(
                f"appid {appid}: resposta inválida ({type(exc).__name__})"
            ) from exc
        if attempt < max_retries:
            delay = backoff * 2 ** (attempt - 1)
            logger.warning("appid %s: tentativa %d falhou (%s); nova em %.1fs",
                           appid, attempt, last, delay)
            sleep(delay)
    raise SteamError(f"appid {appid}: falha após {max_retries} tentativas ({last})")


def fetch_deal(appid: int, fallback_name: str = "", *, session: Any = None,
               timeout: float = 10.0, max_retries: int = 3, backoff: float = 2.0,
               sleep: Callable[[float], None] = time.sleep) -> Deal:
    payload = _get_json(appid, session, timeout, max_retries, backoff, sleep)
    return parse_deal(appid, payload, fallback_name or f"App {appid}")
