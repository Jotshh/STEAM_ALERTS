from datetime import datetime, timedelta, timezone

import pytest

from steam_alert.alert_manager import AlertState
from steam_alert.deal_detector import Action, evaluate

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)


def state(discount=50, on_sale=True, age=timedelta(days=1)):
    return AlertState(discount, 10000, on_sale, NOW - age)


def test_sale_above_threshold(make_deal):
    d = evaluate(make_deal(60), 50, None, NOW)
    assert d.action == Action.NEW_SALE and d.should_notify


def test_sale_equal_threshold(make_deal):
    assert evaluate(make_deal(50), 50, None, NOW).action == Action.NEW_SALE


def test_discount_below_threshold(make_deal):
    d = evaluate(make_deal(30), 50, None, NOW)
    assert d.action == Action.NO_SALE and not d.should_notify


def test_no_sale(make_deal):
    assert evaluate(make_deal(0), 20, None, NOW).action == Action.NO_SALE


def test_unavailable_and_free(make_deal):
    assert evaluate(make_deal(50, available=False), 20, None, NOW).action == Action.NO_SALE
    assert evaluate(make_deal(50, is_free=True), 20, None, NOW).action == Action.NO_SALE


def test_already_notified_same_discount(make_deal):
    d = evaluate(make_deal(50), 20, state(50), NOW)
    assert d.action == Action.DUPLICATE and not d.should_notify and d.is_on_sale


@pytest.mark.parametrize("age,expected", [
    (timedelta(days=6, hours=23), Action.DUPLICATE),
    (timedelta(days=7), Action.REMINDER),
    (timedelta(days=10), Action.REMINDER),
])
def test_same_discount_repeats_only_after_a_week(make_deal, age, expected):
    assert evaluate(make_deal(50), 20, state(50, age=age), NOW).action == expected


@pytest.mark.parametrize("new", [60, 40])
def test_any_discount_change_notifies(make_deal, new):
    d = evaluate(make_deal(new), 20, state(50), NOW)
    assert d.action == Action.DISCOUNT_CHANGED and d.previous_discount == 50


def test_change_notifies_even_right_after_alert(make_deal):
    d = evaluate(make_deal(55), 20, state(50, age=timedelta(minutes=30)), NOW)
    assert d.should_notify


def test_sale_ended(make_deal):
    d = evaluate(make_deal(0), 20, state(50), NOW)
    assert d.action == Action.SALE_ENDED and not d.is_on_sale


def test_drop_below_threshold_ends_sale(make_deal):
    assert evaluate(make_deal(10), 20, state(50), NOW).action == Action.SALE_ENDED


def test_new_sale_after_ended(make_deal):
    ended = state(0, on_sale=False, age=timedelta(days=1))
    assert evaluate(make_deal(50), 20, ended, NOW).action == Action.NEW_SALE
