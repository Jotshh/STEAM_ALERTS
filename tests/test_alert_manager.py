import json
from datetime import datetime, timedelta, timezone

import pytest

from steam_alert.alert_manager import AlertStore, AlertStoreError
from steam_alert.deal_detector import Action, Decision

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)


def test_missing_file_is_empty(tmp_path):
    store = AlertStore(tmp_path / "alerts.json")
    store.load()
    assert store.get(1) is None


def test_persistence_roundtrip(tmp_path, make_deal):
    path = tmp_path / "alerts.json"
    store = AlertStore(path)
    store.load()
    store.apply(make_deal(50), Decision(Action.NEW_SALE), NOW)
    assert store.save() is True

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["1091500"]["last_notified"] == "2026-11-19T18:00:00+00:00"

    again = AlertStore(path)
    again.load()
    s = again.get(1091500)
    assert (s.last_discount, s.last_price, s.is_on_sale, s.last_notified) == (50, 10000, True, NOW)
    assert again.save() is False


def test_duplicate_keeps_last_notified(tmp_path, make_deal):
    store = AlertStore(tmp_path / "a.json")
    store.apply(make_deal(50), Decision(Action.NEW_SALE), NOW)
    store.apply(make_deal(50), Decision(Action.DUPLICATE), NOW + timedelta(days=1))
    s = store.get(1091500)
    assert s.last_notified == NOW and s.is_on_sale


def test_ended_updates_state(tmp_path, make_deal):
    store = AlertStore(tmp_path / "a.json")
    store.apply(make_deal(50), Decision(Action.NEW_SALE), NOW)
    store.apply(make_deal(0), Decision(Action.SALE_ENDED), NOW + timedelta(days=1))
    s = store.get(1091500)
    assert not s.is_on_sale and s.last_discount == 0 and s.last_notified == NOW


def test_naive_timestamp_assumed_utc(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"1091500": {
        "last_discount": 50, "last_price": 4999, "is_on_sale": True,
        "last_notified": "2026-11-19T18:00:00"}}))
    store = AlertStore(path)
    store.load()
    assert store.get(1091500).last_notified == NOW


@pytest.mark.parametrize("content", [
    "{oops", "[]", '{"1": {"last_discount": "x", "is_on_sale": true}}', '{"1": 5}',
])
def test_corrupt_file_raises(tmp_path, content):
    path = tmp_path / "a.json"
    path.write_text(content)
    with pytest.raises(AlertStoreError):
        AlertStore(path).load()
