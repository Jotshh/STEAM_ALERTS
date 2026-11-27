from datetime import datetime, timezone

import pytest
import requests

from steam_alert.alert_manager import LowestPrice, PriceHistoryUpdate
from steam_alert.discord_client import DiscordError, build_embed, format_price, send_alert

NOW = datetime(2026, 11, 19, 21, 0, tzinfo=timezone.utc)
URL = "https://discord.com/api/webhooks/123/SECRET"


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.headers = status, body or {}, {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, items):
        self.items, self.calls = list(items), []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_format_price():
    assert format_price(100) == "R$ 1,00"
    assert format_price(123456) == "R$ 1.234,56"
    assert format_price(5) == "R$ 0,05"


def test_embed_content(make_deal):
    embed = build_embed(make_deal(75), NOW)
    assert embed["title"] == "Cyberpunk 2077"
    assert embed["author"]["name"] == "🎮 Promoção na Steam 🎮"
    assert "~~R$ 199,99~~" in embed["description"]
    assert "75% OFF" in embed["description"] and "R$ 149,99" in embed["description"]
    assert embed["url"].endswith("/app/1091500")
    assert embed["image"]["url"] and embed["color"]
    assert "18:00" in embed["footer"]["text"]
    assert "Ver promoção na Steam" in embed["fields"][-1]["value"]


def test_embed_shows_previous_discount(make_deal):
    embed = build_embed(make_deal(60), NOW, previous_discount=50)
    assert any("50% → 60%" in f["value"] for f in embed["fields"])


def test_embed_highlights_new_lowest_price(make_deal):
    previous = LowestPrice(12000, "BRL", NOW)
    update = PriceHistoryUpdate(
        LowestPrice(9999, "BRL", NOW), previous, True, False
    )

    embed = build_embed(make_deal(50), NOW, price_update=update)

    record_field = next(
        field for field in embed["fields"]
        if field["name"] == "✨ NOVO MENOR PREÇO REGISTRADO!"
    )
    assert "R$ 99,99" in record_field["value"]
    assert "R$ 120,00" in record_field["value"]
    assert embed["color"] == 0xF1C40F
    assert "Ver promoção na Steam" in embed["fields"][-1]["value"]


def test_embed_distinguishes_first_observation_from_steam_record(make_deal):
    update = PriceHistoryUpdate(LowestPrice(9999, "BRL", NOW), None, False, True)

    embed = build_embed(make_deal(50), NOW, price_update=update)

    history_field = next(
        field for field in embed["fields"]
        if field["name"] == "Menor preço observado"
    )
    assert "Primeiro preço observado pelo monitor" in history_field["value"]
    assert "menor preço histórico da Steam" in history_field["value"]


def test_send_success(make_deal):
    session = FakeSession([FakeResponse(204)])
    send_alert(URL, make_deal(), NOW, session=session, sleep=lambda s: None)
    assert len(session.calls) == 1 and session.calls[0][1]["embeds"]
    assert session.calls[0][1]["username"] == "Promoção na Steam"


def test_rate_limit_then_success(make_deal):
    sleeps = []
    session = FakeSession([FakeResponse(429, {"retry_after": 0.5}), FakeResponse(204)])
    send_alert(URL, make_deal(), NOW, session=session, sleep=sleeps.append)
    assert sleeps == [1.0] and len(session.calls) == 2


def test_server_errors_exhaust_retries(make_deal):
    session = FakeSession([FakeResponse(500)] * 3)
    with pytest.raises(DiscordError):
        send_alert(URL, make_deal(), NOW, session=session, sleep=lambda s: None)
    assert len(session.calls) == 3


def test_client_error_not_retried(make_deal):
    session = FakeSession([FakeResponse(400)])
    with pytest.raises(DiscordError):
        send_alert(URL, make_deal(), NOW, session=session, sleep=lambda s: None)
    assert len(session.calls) == 1


def test_errors_do_not_leak_webhook(make_deal):
    err = requests.ConnectionError(f"Max retries exceeded with url: {URL}")
    session = FakeSession([err] * 3)
    with pytest.raises(DiscordError) as info:
        send_alert(URL, make_deal(), NOW, session=session, sleep=lambda s: None)
    assert "SECRET" not in str(info.value)
