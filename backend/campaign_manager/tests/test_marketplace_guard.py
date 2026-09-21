"""ZC-A1 — a campaign from another marketplace must never become an automation here.

`/ads/campaigns` merges Blinkit and Zepto rows, and the automation API is pinned to one
marketplace (`campaign_manager_service.PLATFORM`). Before the guard, a Zepto campaign picked
from that list was saved as a Blinkit automation — and its id queued for Blinkit's ad
account. These pin the rule, with the catalogue lookup stubbed (no DB):

  * a campaign only ANOTHER marketplace knows is refused, with a 400-mapped error;
  * a campaign no catalogue has seen is allowed (one created since the last scrape);
  * a campaign this marketplace knows is allowed.

    python -m campaign_manager.tests.test_marketplace_guard
"""
import asyncio
import uuid

from app.schemas.ads import CampaignRow
from app.services import campaign_manager_service as svc

TENANT = uuid.uuid4()


def _guard(found: set[str]):
    orig = svc.repo.campaign_marketplaces

    async def fake(tenant_id, campaign_id):
        return set(found)

    svc.repo.campaign_marketplaces = fake
    try:
        asyncio.run(svc._require_marketplace(TENANT, 2427461))
    finally:
        svc.repo.campaign_marketplaces = orig


def test_a_campaign_only_zepto_knows_is_refused():
    try:
        _guard({"zepto"})
    except svc.WrongMarketplace as e:
        assert "Zepto" in str(e) and "nothing was created" in str(e)
    else:
        raise AssertionError("a Zepto campaign must not become a Blinkit automation")


def test_the_refusal_is_an_edit_error_so_routes_map_it_to_400():
    assert issubclass(svc.WrongMarketplace, svc.EditError)


def test_an_uncatalogued_campaign_is_allowed():
    """Created since the last scrape — refusing would make it unautomatable until tomorrow."""
    _guard(set())


def test_a_campaign_this_marketplace_knows_is_allowed():
    _guard({svc.PLATFORM})


def test_a_campaign_both_catalogues_know_is_allowed():
    # The id spaces are separate so this should not happen; if it does, this API's own
    # catalogue knowing it is enough.
    _guard({svc.PLATFORM, "zepto"})


def test_every_write_entry_point_runs_the_guard():
    """The four paths that turn a caller's campaign id into an automation or a job."""
    import inspect
    for fn in (svc.create_budget_schedule, svc.create_bid_rule, svc.set_budget_now,
               svc.set_activation_now):
        assert "_require_marketplace(" in inspect.getsource(fn), (
            f"{fn.__name__} must refuse a campaign from another marketplace")


def test_campaign_rows_say_which_marketplace_they_belong_to():
    row = CampaignRow(campaign_id=1, name="x", type=None, status=None, budget_consumed=0,
                      impressions=0, atc=0, quantities_sold=0, ad_sales=0, roas=0)
    assert row.platform == "blinkit"            # the default existing Blinkit rows get
    assert CampaignRow(**{**row.model_dump(), "platform": "zepto"}).platform == "zepto"


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
