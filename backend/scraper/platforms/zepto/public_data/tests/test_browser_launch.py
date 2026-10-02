"""Which browser each shopper-side path launches (2026-09-26).

Zepto's WAF blocks Playwright's default headless shell and lets the FULL Chromium in headless
mode through (see endpoints.BROWSER_CHANNEL). These pin that every Zepto path — the worker
pools via the provider, the ad-hoc session, the bid engine's rank session — asks for the full
build, and that Blinkit keeps the default it has always used. No browser is started: the
Playwright handle is a recorder.

Run:  python -m scraper.platforms.zepto.public_data.tests.test_browser_launch
"""
import asyncio

from scraper.platforms.zepto.public_data import endpoints as ep
from scraper.platforms.zepto.public_data import scraper as zs
from scraper.public.providers import get_provider


class _Browser:
    async def close(self):
        pass


class _Chromium:
    def __init__(self):
        self.calls = []

    async def launch(self, **kw):
        self.calls.append(kw)
        return _Browser()


class _PW:
    def __init__(self):
        self.chromium = _Chromium()


def _launch_kwargs(launcher) -> dict:
    pw = _PW()
    asyncio.run(launcher(pw))
    assert len(pw.chromium.calls) == 1
    return pw.chromium.calls[0]


def test_zepto_launches_the_full_chromium_headless():
    kw = _launch_kwargs(zs.launch_browser)
    assert kw["headless"] is True
    assert kw["channel"] == ep.BROWSER_CHANNEL == "chromium"


def test_the_zepto_worker_pools_launch_through_the_zepto_launcher():
    """Keyword scrape, own-SKU scrape and Explorer all start the browser via the provider."""
    kw = _launch_kwargs(get_provider("zepto").launch_browser)
    assert kw.get("channel") == "chromium"


def test_blinkit_keeps_the_default_browser():
    kw = _launch_kwargs(get_provider("blinkit").launch_browser)
    assert kw["headless"] is True
    assert "channel" not in kw, "Blinkit must not change browser as a side effect"


def test_the_ad_hoc_session_and_the_bid_engine_use_the_zepto_launcher():
    """`open_session` (which the bid engine's `open_position_session` calls) must launch
    through `launch_browser`, not its own copy of the launch call."""
    seen = []
    orig_make, orig_launch = zs._make_session, zs.launch_browser

    async def _launch(pw, proxy=None):
        seen.append("launch_browser")
        return _Browser()

    async def _make(browser, lat, lon, **kw):
        return None                     # "could not open" — nothing else to do here

    zs.launch_browser, zs._make_session = _launch, _make
    try:
        assert asyncio.run(zs.open_session(_PW(), 12.97, 77.59)) is None
    finally:
        zs.launch_browser, zs._make_session = orig_launch, orig_make
    assert seen == ["launch_browser"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} browser-launch tests passed.")
