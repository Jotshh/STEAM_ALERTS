import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from steam_alert.alert_manager import AlertStore
from steam_alert.discord_client import DiscordError
from steam_alert.main import ConfigError, load_games, run
from steam_alert.steam_client import SteamError

T0 = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)
WEBHOOK = "https://discord.com/api/webhooks/1/token"


class Env:
    def __init__(self, tmp_path, make_deal, discount=50, enabled=True):
        self.games = tmp_path / "games.json"
        self.alerts = tmp_path / "alerts.json"
        self.games.write_text(json.dumps([
            {"name": "Cyberpunk 2077", "appid": 1091500, "min_discount": 30, "enabled": enabled}]))
        self.make_deal, self.discount, self.now = make_deal, discount, T0
        self.sent, self.fail_send, self.fail_fetch = [], False, False
        self.initial, self.unavailable, self.invalid_price = 19999, False, False

    def fetch(self, appid, name, **kw):
        if self.fail_fetch:
            raise SteamError("falhou")
        deal = self.make_deal(self.discount, initial=self.initial, appid=appid)
        if self.unavailable:
            return replace(deal, available=False)
        if self.invalid_price:
            return replace(deal, final_price=0)
        return deal

    def send(self, url, deal, now, previous=None, **kw):
        if self.fail_send:
            raise DiscordError("falhou")
        self.sent.append((deal.discount_percent, previous))

    def run(self, **kw):
        return run(self.games, self.alerts, kw.pop("webhook", WEBHOOK), fetch=self.fetch,
                   send=self.send, now_fn=lambda: self.now, sleep=lambda s: None,
                   request_delay=0, **kw)

    def state(self):
        store = AlertStore(self.alerts)
        store.load()
        return store.get(1091500)


@pytest.fixture
def env(tmp_path, make_deal):
    return Env(tmp_path, make_deal)


def test_new_sale_notifies_once_then_waits_a_week(env):
    assert env.run() == 0 and len(env.sent) == 1
    env.now = T0 + timedelta(hours=1)
    env.run()
    assert len(env.sent) == 1
    env.now = T0 + timedelta(days=8)
    env.run()
    assert len(env.sent) == 2


def test_state_survives_between_runs(env):
    env.run()
    assert env.state().is_on_sale and env.state().last_notified == T0


def test_discount_change_notifies_again(env):
    env.run()
    env.discount, env.now = 60, T0 + timedelta(hours=1)
    env.run()
    assert env.sent == [(50, None), (60, 50)]


def test_sale_end_then_new_sale(env):
    env.run()
    env.discount, env.now = 0, T0 + timedelta(hours=1)
    env.run()
    assert not env.state().is_on_sale
    env.discount, env.now = 50, T0 + timedelta(hours=2)
    env.run()
    assert len(env.sent) == 2


def test_discord_failure_keeps_state_for_retry(env):
    env.fail_send = True
    assert env.run() == 1
    state = env.state()
    assert state is not None and not state.is_on_sale and state.last_notified is None
    assert state.lowest_prices["BRL"].price == 10000
    env.fail_send = False
    env.now = T0 + timedelta(minutes=30)
    assert env.run() == 0 and len(env.sent) == 1


def test_dry_run_changes_nothing(env):
    assert env.run(dry_run=True, webhook=None) == 0
    assert env.sent == [] and not env.alerts.exists()


def test_steam_failure_returns_error(env):
    env.fail_fetch = True
    assert env.run() == 1 and env.sent == []


def test_minimum_price_updates_below_discount_threshold_without_alert(env):
    env.discount = 15

    assert env.run() == 0

    assert env.sent == []
    assert env.state().lowest_prices["BRL"].price == 17000


def test_steam_failure_preserves_existing_price_history(env):
    store = AlertStore(env.alerts)
    store.load()
    store.record_lowest_price(env.make_deal(50, initial=20000), T0)
    store.save()
    env.fail_fetch = True

    assert env.run() == 1

    assert env.state().lowest_prices["BRL"].price == 10000


def test_unavailable_game_preserves_price_and_alert_history(env):
    assert env.run() == 0
    previous = env.state()
    env.unavailable = True
    env.now = T0 + timedelta(hours=1)

    assert env.run() == 0

    current = env.state()
    assert current.lowest_prices == previous.lowest_prices
    assert current.is_on_sale == previous.is_on_sale
    assert current.last_notified == previous.last_notified


def test_invalid_price_preserves_existing_minimum(env):
    assert env.run() == 0
    env.invalid_price = True
    env.now = T0 + timedelta(hours=1)

    assert env.run() == 0

    assert env.state().lowest_prices["BRL"].price == 10000


def test_new_record_alone_does_not_send_duplicate_notification(env):
    assert env.run() == 0
    env.initial = 17999
    env.now = T0 + timedelta(hours=1)

    assert env.run() == 0

    assert len(env.sent) == 1
    assert env.state().lowest_prices["BRL"].price == 9000


def test_disabled_game_ignored(tmp_path, make_deal):
    e = Env(tmp_path, make_deal, enabled=False)
    assert e.run() == 0 and e.sent == []


@pytest.mark.parametrize("webhook", [None, "", "http://discord.com/api/webhooks/1/x",
                                     "https://evil.example/api/webhooks/1/x"])
def test_invalid_webhook(env, webhook):
    assert env.run(webhook=webhook) == 2


@pytest.mark.parametrize("content", [
    "{x", "{}", '[1]', '[{"name": "", "appid": 1, "min_discount": 10}]',
    '[{"name": "a", "appid": "1", "min_discount": 10}]',
    '[{"name": "a", "appid": 1, "min_discount": 101}]',
    '[{"name": "a", "appid": 1, "min_discount": 10, "enabled": "yes"}]',
    '[{"name": "a", "appid": 1, "min_discount": 10}, {"name": "b", "appid": 1, "min_discount": 10}]',
])
def test_invalid_games_config(tmp_path, content):
    path = tmp_path / "games.json"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_games(path)


def test_default_config_is_valid():
    from steam_alert.main import DEFAULT_GAMES
    games = load_games(DEFAULT_GAMES)
    assert games
    assert all(game.enabled for game in games)
