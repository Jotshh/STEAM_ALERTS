"""Persistência do estado dos alertas em data/alerts.json."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .deal_detector import Decision
from .steam_client import Deal

logger = logging.getLogger(__name__)


class AlertStoreError(Exception):
    """Arquivo de histórico inválido."""


@dataclass
class AlertState:
    last_discount: int
    last_price: int | None
    is_on_sale: bool
    last_notified: datetime | None

    def to_dict(self) -> dict:
        return {
            "last_discount": self.last_discount,
            "last_price": self.last_price,
            "is_on_sale": self.is_on_sale,
            "last_notified": (
                self.last_notified.astimezone(timezone.utc).isoformat(timespec="seconds")
                if self.last_notified else None
            ),
        }

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
        except (KeyError, TypeError, ValueError) as exc:
            raise AlertStoreError("entrada de histórico com campos inválidos") from exc
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return cls(discount, price, on_sale, parsed)


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
        )

    def save(self) -> bool:
        """Grava só se houve mudança. Retorna True quando o arquivo foi alterado."""
        text = json.dumps(
            {k: v.to_dict() for k, v in self._states.items()},
            indent=2, sort_keys=True, ensure_ascii=False,
        ) + "\n"
        current = self.path.read_text(encoding="utf-8") if self.path.exists() else None
        if current == text:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.path)
        logger.info("Histórico salvo em %s", self.path)
        return True
