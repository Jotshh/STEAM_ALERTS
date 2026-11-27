import json
from dataclasses import replace
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


def test_first_valid_price_is_recorded_and_persisted(tmp_path, make_deal):
    path = tmp_path / "alerts.json"
    store = AlertStore(path)
    store.load()

    update = store.record_lowest_price(make_deal(15), NOW)

    assert update is not None and update.first_observation
    assert not update.is_new_record and update.previous is None
    assert update.record.price == 17000
    assert update.record.currency == "BRL"
    assert update.record.observed_at == NOW
    assert store.save()

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["1091500"]["lowest_prices"]["BRL"] == {
        "price": 17000,
        "observed_at": "2026-11-19T18:00:00+00:00",
    }
    restarted = AlertStore(path)
    restarted.load()
    assert restarted.get(1091500).lowest_prices["BRL"] == update.record


def test_lower_price_updates_record_and_reports_new_low(tmp_path, make_deal):
    store = AlertStore(tmp_path / "alerts.json")
    store.record_lowest_price(make_deal(50, initial=20000), NOW)

    update = store.record_lowest_price(
        make_deal(50, initial=18000), NOW + timedelta(hours=1)
    )

    assert update is not None and update.is_new_record
    assert update.previous is not None and update.previous.price == 10000
    assert update.record.price == 9000
    assert update.record.observed_at == NOW + timedelta(hours=1)


def test_higher_price_preserves_lowest_record(tmp_path, make_deal):
    store = AlertStore(tmp_path / "alerts.json")
    first = store.record_lowest_price(make_deal(50, initial=20000), NOW)

    update = store.record_lowest_price(
        make_deal(50, initial=24000), NOW + timedelta(hours=1)
    )

    assert first is not None and update is not None
    assert not update.is_new_record and not update.first_observation
    assert update.record == first.record
    assert store.get(1091500).lowest_prices["BRL"] == first.record


def test_currency_change_keeps_independent_price_history(tmp_path, make_deal):
    store = AlertStore(tmp_path / "alerts.json")
    store.record_lowest_price(make_deal(50, initial=20000), NOW)
    usd_deal = replace(make_deal(50, initial=18000), currency="USD")

    update = store.record_lowest_price(usd_deal, NOW + timedelta(hours=1))

    assert update is not None and update.first_observation
    assert not update.is_new_record
    assert set(store.get(1091500).lowest_prices) == {"BRL", "USD"}


@pytest.mark.parametrize("changes", [
    {"final_price": 0},
    {"final_price": 1.5},
    {"final_price": True},
    {"available": False},
    {"is_free": True},
    {"currency": ""},
    {"currency": None},
])
def test_invalid_or_unavailable_price_does_not_change_history(
        tmp_path, make_deal, changes):
    store = AlertStore(tmp_path / "alerts.json")
    original = store.record_lowest_price(make_deal(50), NOW)
    invalid_deal = replace(make_deal(20), **changes)

    assert store.record_lowest_price(invalid_deal, NOW + timedelta(hours=1)) is None
    assert store.get(1091500).lowest_prices["BRL"] == original.record


def test_existing_alert_json_remains_compatible(tmp_path, make_deal):
    path = tmp_path / "alerts.json"
    legacy = {
        "last_discount": 50,
        "last_price": 9999,
        "is_on_sale": True,
        "last_notified": "2026-11-19T18:00:00+00:00",
    }
    path.write_text(json.dumps({"1091500": legacy}), encoding="utf-8")
    store = AlertStore(path)
    store.load()

    assert store.get(1091500).lowest_prices == {}
    store.record_lowest_price(make_deal(50), NOW)
    store.save()

    stored = json.loads(path.read_text(encoding="utf-8"))["1091500"]
    assert {key: stored[key] for key in legacy} == legacy
    assert stored["lowest_prices"]["BRL"]["price"] == 10000


def test_atomic_write_failure_keeps_previous_json(tmp_path, make_deal, monkeypatch):
    path = tmp_path / "alerts.json"
    original = {
        "1": {
            "last_discount": 0,
            "last_price": 1234,
            "is_on_sale": False,
            "last_notified": None,
        }
    }
    original_text = json.dumps(original)
    path.write_text(original_text, encoding="utf-8")
    store = AlertStore(path)
    store.load()
    store.record_lowest_price(replace(make_deal(50), appid=1), NOW)

    def fail_replace(source, destination):
        raise OSError(f"simulated replace failure: {source} -> {destination}")

    monkeypatch.setattr("steam_alert.alert_manager.os.replace", fail_replace)
    with pytest.raises(AlertStoreError):
        store.save()

    assert path.read_text(encoding="utf-8") == original_text


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
