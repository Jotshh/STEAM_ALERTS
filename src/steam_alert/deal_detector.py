"""Regras de detecção de promoções (lógica pura, sem I/O)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from .steam_client import Deal

if TYPE_CHECKING:
    from .alert_manager import AlertState

REPEAT_AFTER = timedelta(days=7)


class Action(str, Enum):
    NEW_SALE = "new_sale"
    DISCOUNT_CHANGED = "discount_changed"
    REMINDER = "reminder"
    DUPLICATE = "duplicate"
    SALE_ENDED = "sale_ended"
    NO_SALE = "no_sale"


NOTIFY_ACTIONS = {Action.NEW_SALE, Action.DISCOUNT_CHANGED, Action.REMINDER}
ON_SALE_ACTIONS = NOTIFY_ACTIONS | {Action.DUPLICATE}


@dataclass(frozen=True)
class Decision:
    action: Action
    previous_discount: int | None = None

    @property
    def should_notify(self) -> bool:
        return self.action in NOTIFY_ACTIONS

    @property
    def is_on_sale(self) -> bool:
        return self.action in ON_SALE_ACTIONS


def is_valid_sale(deal: Deal, min_discount: int) -> bool:
    return (
        deal.available
        and not deal.is_free
        and deal.discount_percent > 0
        and deal.final_price < deal.initial_price
        and deal.discount_percent >= min_discount
    )


def evaluate(deal: Deal, min_discount: int, state: AlertState | None,
             now: datetime, repeat_after: timedelta = REPEAT_AFTER) -> Decision:
    was_on_sale = state is not None and state.is_on_sale

    if not is_valid_sale(deal, min_discount):
        return Decision(Action.SALE_ENDED if was_on_sale else Action.NO_SALE)

    if not was_on_sale:
        return Decision(Action.NEW_SALE)

    if deal.discount_percent != state.last_discount:
        return Decision(Action.DISCOUNT_CHANGED, state.last_discount)

    if state.last_notified is None or now - state.last_notified >= repeat_after:
        return Decision(Action.REMINDER)

    return Decision(Action.DUPLICATE)
