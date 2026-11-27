import pytest
import requests

from steam_alert.steam_client import SteamError, fetch_deal, parse_deal

APPID = 1091500


def payload(**data):
    base = {
        "name": "Cyberpunk 2077",
        "is_free": False,
        "header_image": "https://img.example/h.jpg",
        "price_overview": {"currency": "BRL", "initial": 19999,
                           "final": 4999, "discount_percent": 75},
    }
    base.update(data)
    return {str(APPID): {"success": True, "data": base}}


class FakeResponse:
    def __init__(self, status=200, body=None, invalid=False):
        self.status_code, self._body, self._invalid = status, body, invalid

    def json(self):
        if self._invalid:
            raise ValueError("json inválido")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, items):
        self.items, self.calls = list(items), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_fetch_success():
    session = FakeSession([FakeResponse(body=payload())])
    deal = fetch_deal(APPID, "x", session=session, sleep=lambda s: None)
    assert (deal.name, deal.initial_price, deal.final_price) == ("Cyberpunk 2077", 19999, 4999)
    assert deal.discount_percent == 75 and deal.available and deal.savings == 15000
    assert deal.url.endswith(f"/app/{APPID}")
    _, params, timeout = session.calls[0]
    assert params == {"appids": APPID, "cc": "br", "l": "brazilian"} and timeout


@pytest.mark.parametrize("body", [None, [], {}, {"1091500": {}}, {"1091500": {"success": True}}])
def test_invalid_payload(body):
    with pytest.raises(SteamError):
        parse_deal(APPID, body, "x")


def test_invalid_price_values():
    with pytest.raises(SteamError):
        parse_deal(APPID, payload(price_overview={"initial": "abc", "final": 1,
                                                  "discount_percent": 1}), "x")


@pytest.mark.parametrize("price", [
    {"currency": "BRL", "initial": 100, "final": 50.5, "discount_percent": 50},
    {"currency": "", "initial": 100, "final": 50, "discount_percent": 50},
    {"currency": "BRL", "initial": True, "final": 50, "discount_percent": 50},
])
def test_invalid_price_shape_is_rejected(price):
    with pytest.raises(SteamError):
        parse_deal(APPID, payload(price_overview=price), "x")


def test_non_json_response_raises():
    with pytest.raises(SteamError):
        fetch_deal(APPID, session=FakeSession([FakeResponse(invalid=True)]),
                   sleep=lambda s: None)


def test_game_without_price():
    deal = parse_deal(APPID, payload(price_overview=None), "x")
    assert not deal.available and deal.discount_percent == 0


def test_free_game():
    deal = parse_deal(APPID, payload(is_free=True), "x")
    assert deal.is_free and deal.available


def test_unavailable_in_region():
    deal = parse_deal(APPID, {str(APPID): {"success": False}}, "Meu Jogo")
    assert not deal.available and deal.name == "Meu Jogo"


def test_retry_then_success():
    sleeps = []
    session = FakeSession([FakeResponse(500), requests.Timeout("t"),
                           FakeResponse(body=payload())])
    deal = fetch_deal(APPID, session=session, sleep=sleeps.append, backoff=2.0)
    assert deal.discount_percent == 75
    assert sleeps == [2.0, 4.0]


def test_retries_exhausted():
    session = FakeSession([FakeResponse(503)] * 3)
    with pytest.raises(SteamError):
        fetch_deal(APPID, session=session, sleep=lambda s: None)
    assert len(session.calls) == 3


def test_client_error_not_retried():
    session = FakeSession([FakeResponse(404)])
    with pytest.raises(SteamError):
        fetch_deal(APPID, session=session, sleep=lambda s: None)
    assert len(session.calls) == 1
