import pytest

from steam_alert.steam_client import Deal


@pytest.fixture
def make_deal():
    def factory(discount=50, initial=19999, appid=1091500, name="Cyberpunk 2077",
                available=True, is_free=False):
        final = initial - initial * discount // 100
        return Deal(
            appid=appid, name=name, currency="BRL", initial_price=initial,
            final_price=final, discount_percent=discount,
            url=f"https://store.steampowered.com/app/{appid}",
            image_url="https://img.example/x.jpg", available=available, is_free=is_free,
        )
    return factory
