import json
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

    def fetch(self, appid, name, **kw):
        if self.fail_fetch:
            raise SteamError("falhou")
        return self.make_deal(self.discount, appid=appid)

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
    assert env.state() is None
    env.fail_send = False
    env.now = T0 + timedelta(minutes=30)
    assert env.run() == 0 and len(env.sent) == 1


def test_dry_run_changes_nothing(env):
    assert env.run(dry_run=True, webhook=None) == 0
    assert env.sent == [] and not env.alerts.exists()


def test_steam_failure_returns_error(env):
    env.fail_fetch = True
    assert env.run() == 1 and env.sent == []


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
    assert len(load_games(DEFAULT_GAMES)) == 3
