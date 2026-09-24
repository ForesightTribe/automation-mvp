"""ZC-A1 / D1 — a campaign from another marketplace must never become an automation here.

`/ads/campaigns` merges Blinkit and Zepto rows, and every automation call names ONE
marketplace in its address (`/campaign-manager/<marketplace>/…`, no default — ZC-D1).
Before the guard, a Zepto campaign picked from that list was saved as a Blinkit automation —
and its id queued for Blinkit's ad account. These pin the rule, with the catalogue lookup
stubbed (no DB):

  * a campaign only the OTHER marketplace knows is refused, with a 400-mapped error;
  * a campaign no catalogue has seen is allowed (one created since the last scrape);
  * a campaign the address's marketplace knows is allowed — on either marketplace.

    python -m campaign_manager.tests.test_marketplace_guard
"""
import asyncio
import uuid

import pydantic

from app.schemas.ads import CampaignRow
from app.services import campaign_manager_service as svc

TENANT = uuid.uuid4()


def _guard(found: set[str], marketplace: str):
    orig = svc.repo.campaign_marketplaces

    async def fake(tenant_id, campaign_id):
        return set(found)

    svc.repo.campaign_marketplaces = fake
    try:
        asyncio.run(svc._require_marketplace(TENANT, 2427461, marketplace))
    finally:
        svc.repo.campaign_marketplaces = orig


def _refused(found: set[str], marketplace: str) -> str:
    try:
        _guard(found, marketplace)
    except svc.WrongMarketplace as e:
        return str(e)
    raise AssertionError(f"{found} campaign must be refused under {marketplace}")


def test_a_zepto_campaign_is_refused_under_blinkit():
    said = _refused({"zepto"}, "blinkit")
    assert "Zepto" in said and "nothing was done" in said


def test_a_blinkit_campaign_is_refused_under_zepto():
    """The guard is symmetric now that Zepto has its own address."""
    said = _refused({"blinkit"}, "zepto")
    assert "Blinkit" in said and "not a Zepto one" in said


def test_the_refusal_is_an_edit_error_so_routes_map_it_to_400():
    assert issubclass(svc.WrongMarketplace, svc.EditError)


def test_an_uncatalogued_campaign_is_allowed():
    """Created since the last scrape — refusing would make it unautomatable until tomorrow."""
    _guard(set(), "blinkit")
    _guard(set(), "zepto")


def test_a_campaign_this_marketplace_knows_is_allowed():
    _guard({"blinkit"}, "blinkit")
    _guard({"zepto"}, "zepto")


def test_a_campaign_both_catalogues_know_is_allowed():
    # The id spaces are separate so this should not happen; if it does, the address's own
    # catalogue knowing it is enough.
    _guard({"blinkit", "zepto"}, "zepto")


def test_every_write_entry_point_runs_the_guard():
    """The four paths that turn a caller's campaign id into an automation or a job."""
    import inspect
    for fn in (svc.create_budget_schedule, svc.create_bid_rule, svc.set_budget_now,
               svc.set_activation_now):
        assert "_require_marketplace(" in inspect.getsource(fn), (
            f"{fn.__name__} must refuse a campaign from another marketplace")


def test_campaign_rows_must_say_which_marketplace_they_belong_to():
    """No default any more (ZC-D1): a row without `platform` is a bug to surface, not a
    Blinkit row to assume."""
    fields = dict(campaign_id=1, name="x", type=None, status=None, budget_consumed=0,
                  impressions=0, atc=0, quantities_sold=0, ad_sales=0, roas=0)
    try:
        CampaignRow(**fields)
    except pydantic.ValidationError:
        pass
    else:
        raise AssertionError("a row without a marketplace must not validate")
    assert CampaignRow(**fields, platform="zepto").platform == "zepto"


def test_the_service_has_no_default_marketplace():
    """The constant that made every automation a Blinkit one is gone for good."""
    assert not hasattr(svc, "PLATFORM")


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} marketplace-guard tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
