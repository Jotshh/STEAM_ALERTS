"""Persistência do estado dos alertas em data/alerts.json."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .deal_detector import Decision
from .steam_client import Deal

logger = logging.getLogger(__name__)


class AlertStoreError(Exception):
    """Arquivo de histórico inválido."""


@dataclass(frozen=True)
class LowestPrice:
    price: int
    currency: str
    observed_at: datetime

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(
                timespec="seconds"
            ),
        }


@dataclass(frozen=True)
class PriceHistoryUpdate:
    record: LowestPrice
    previous: LowestPrice | None
    is_new_record: bool
    first_observation: bool


@dataclass
class AlertState:
    last_discount: int
    last_price: int | None
    is_on_sale: bool
    last_notified: datetime | None
    lowest_prices: dict[str, LowestPrice] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = {
            "last_discount": self.last_discount,
            "last_price": self.last_price,
            "is_on_sale": self.is_on_sale,
            "last_notified": (
                self.last_notified.astimezone(timezone.utc).isoformat(timespec="seconds")
                if self.last_notified else None
            ),
        }
        if self.lowest_prices:
            result["lowest_prices"] = {
                currency: record.to_dict()
                for currency, record in sorted(self.lowest_prices.items())
            }
        return result

    @classmethod
    def from_dict(cls, raw: object) -> AlertState:
        if not isinstance(raw, dict):
            raise AlertStoreError("entrada de histórico inválida")
        try:
            discount = raw["last_discount"]
            price = raw.get("last_price")
            on_sale = raw["is_on_sale"]
            notified = raw.get("last_notified")
            if (isinstance(discount, bool) or not isinstance(discount, int)
                    or not isinstance(on_sale, bool)
                    or not (price is None or (isinstance(price, int) and not isinstance(price, bool)))):
                raise TypeError
            parsed = datetime.fromisoformat(notified) if notified else None
            raw_lowest_prices = raw.get("lowest_prices", {})
        except (KeyError, TypeError, ValueError) as exc:
            raise AlertStoreError("entrada de histórico com campos inválidos") from exc
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if not isinstance(raw_lowest_prices, dict):
            raise AlertStoreError("entrada de histórico com menores preços inválidos")

        lowest_prices: dict[str, LowestPrice] = {}
        for currency, item in raw_lowest_prices.items():
            if (not isinstance(currency, str) or len(currency) != 3
                    or not currency.isascii() or not currency.isalpha()
                    or not isinstance(item, dict)):
                raise AlertStoreError("entrada de histórico com menores preços inválidos")
            try:
                amount = item["price"]
                observed_at = datetime.fromisoformat(item["observed_at"])
                if (isinstance(amount, bool) or not isinstance(amount, int)
                        or amount <= 0):
                    raise TypeError
            except (KeyError, TypeError, ValueError) as exc:
                raise AlertStoreError(
                    "entrada de histórico com menores preços inválidos"
                ) from exc
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            code = currency.upper()
            lowest_prices[code] = LowestPrice(amount, code, observed_at)
        return cls(discount, price, on_sale, parsed, lowest_prices)


class AlertStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._states: dict[str, AlertState] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._states = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise AlertStoreError(f"{self.path} não é um JSON válido") from exc
        if not isinstance(raw, dict):
            raise AlertStoreError(f"{self.path} deve conter um objeto JSON")
        self._states = {str(k): AlertState.from_dict(v) for k, v in raw.items()}

    def get(self, appid: int) -> AlertState | None:
        return self._states.get(str(appid))

    def record_lowest_price(self, deal: Deal, now: datetime) -> PriceHistoryUpdate | None:
        if (not deal.available or deal.is_free
                or isinstance(deal.final_price, bool)
                or not isinstance(deal.final_price, int)
                or deal.final_price <= 0
                or not isinstance(deal.currency, str)):
            return None
        currency = deal.currency.strip().upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            return None
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        key = str(deal.appid)
        state = self._states.get(key)
        if state is None:
            state = AlertState(0, None, False, None)
            self._states[key] = state
        previous = state.lowest_prices.get(currency)
        if previous is None:
            if state.lowest_prices:
                logger.warning(
                    "appid %s: moeda %s não comparada com histórico em outra moeda; "
                    "iniciando histórico separado",
                    deal.appid, currency,
                )
            record = LowestPrice(deal.final_price, currency, now)
            state.lowest_prices[currency] = record
            return PriceHistoryUpdate(record, None, False, True)

        if deal.final_price < previous.price:
            record = LowestPrice(deal.final_price, currency, now)
            state.lowest_prices[currency] = record
            return PriceHistoryUpdate(record, previous, True, False)

        return PriceHistoryUpdate(previous, None, False, False)

    def apply(self, deal: Deal, decision: Decision, now: datetime) -> None:
        previous = self._states.get(str(deal.appid))
        notified = previous.last_notified if previous else None
        if decision.should_notify:
            notified = now
        self._states[str(deal.appid)] = AlertState(
            last_discount=deal.discount_percent,
            last_price=deal.final_price if deal.available else None,
            is_on_sale=decision.is_on_sale,
            last_notified=notified,
            lowest_prices=previous.lowest_prices.copy() if previous else {},
        )

    def save(self) -> bool:
        """Grava só se houve mudança. Retorna True quando o arquivo foi alterado."""
        text = json.dumps(
            {k: v.to_dict() for k, v in self._states.items()},
            indent=2, sort_keys=True, ensure_ascii=False,
        ) + "\n"
        tmp_path: Path | None = None
        try:
            current = self.path.read_text(encoding="utf-8") if self.path.exists() else None
            if current == text:
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, self.path)
        except OSError as exc:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except FileNotFoundError:
                    pass
            raise AlertStoreError(f"falha ao salvar {self.path}") from exc
        logger.info("Histórico salvo em %s", self.path)
        return True
