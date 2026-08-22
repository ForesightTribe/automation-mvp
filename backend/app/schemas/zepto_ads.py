"""Zepto-specific ad response shapes.

Kept out of `app/schemas/ads.py` because that file's models describe Blinkit's
ad plane and are owned elsewhere. Where Zepto's grain matches Blinkit's closely
enough (summary tiles, campaigns, performance points) the existing shared models
are reused as-is; only keywords need their own, for the reasons below.
"""
from datetime import date

from pydantic import BaseModel


class ZeptoKeywordRow(BaseModel):
    """One Zepto keyword + match type, summed over the requested window.

    Separate from `ads.KeywordRow` rather than merged into it, because the two
    marketplaces report keywords differently enough that sharing one model would
    mean making Blinkit's columns nullable:

    * Zepto's keyword table is **brand-wide** — the response carries no campaign
      id at all, so a keyword cannot be attributed to the campaign that bid it.
      Blinkit's comes from a per-campaign report and always has one.
    * Blinkit splits sales and add-to-carts into direct (the advertised SKU) and
      indirect (other SKUs). Zepto reports only totals, so there is no honest
      value to put in either half.
    * Blinkit's rows are a range-aggregate snapshot; Zepto's are daily and summed
      over whatever window is asked for.

    Going the other way, Zepto reports clicks, CTR and CPC, which Blinkit does
    not — those would be permanently null on a shared model.
    """

    keyword: str
    match_type: str | None = None
    # Which ad types the keyword was bid under. A list, not a single value:
    # Zepto's tabs are disjoint sets of campaigns, but the same keyword can be
    # bid in more than one of them, and the row sums across them.
    ad_types: list[str] = []

    impressions: int
    clicks: int
    spend: float
    sales: float
    atc: int
    units_sold: int

    # Recomputed from the summed components, not averaged across days.
    ctr: float | None = None
    cpc: float | None = None
    cpm: float | None = None
    roas: float | None = None


class ZeptoBudgetSplitRow(BaseModel):
    """Spend and recomputed RoAS for one Zepto campaign type over the window.

    Same field names as `ads.BudgetSplitRow` so the frontend donut can render
    either without branching — but a separate model, so Blinkit's schema is not
    shared across marketplaces. `campaign_type` here is PLA / Display, against
    Blinkit's PRODUCT_LISTING / PRODUCT_RECOMMENDATION.
    """

    campaign_type: str | None
    budget_consumed: float
    ad_sales: float
    roas: float


class ZeptoSovRow(BaseModel):
    """One campaign's share of voice and ad position, as of the latest scrape.

    Not comparable to `ads.SponsoredSovRow`, which is Blinkit's: that is per
    KEYWORD and carries search volumes, and its `date` is a real observation
    date. Zepto reports SOV per CAMPAIGN, with no keyword and no search volume,
    and as a trailing figure that ignores the requested window entirely — hence
    `as_of` rather than `date`, so the UI can say what the number describes.
    """

    campaign_id: int
    campaign_name: str | None = None
    campaign_type: str | None = None
    # Percentage, as Zepto reports it — not rescaled.
    sov: float | None = None
    # Average position of the ad in results. Lower is better.
    ad_position: float | None = None
    as_of: date


class ZeptoProductRow(BaseModel):
    """One advertised SKU, summed over the window.

    No Blinkit counterpart: Blinkit's ad plane stops at campaign and keyword
    level, so there is no shared model to reuse. `product_category` is the
    SKU's retail category ("Breads & Buns"), not the ad type.
    """

    product_variant_id: str
    product_name: str | None = None
    image_link: str | None = None
    product_category: str | None = None
    # The ad types this SKU ran under, so a combined row still shows where its
    # spend came from.
    ad_types: list[str] = []

    spend: float
    sales: float
    impressions: int
    clicks: int
    units_sold: int
    atc: int

    ctr: float | None = None
    cpc: float | None = None
    cpm: float | None = None
    roas: float | None = None


class ZeptoBreakdownRow(BaseModel):
    """One bucket of a Zepto ad breakdown — a retail category, city, or page.

    One model for all three because the underlying views are identical: a name
    plus the same metrics. `name` is the bucket; which kind it is comes from the
    `dimension` the caller asked for.
    """

    name: str
    # Ad types contributing to this row. Genuinely plural in practice — Cheese
    # ran under both sponsored products and sponsored brands on 19-Aug-2026.
    ad_types: list[str] = []

    spend: float
    sales: float
    impressions: int
    clicks: int
    units_sold: int
    atc: int

    ctr: float | None = None
    cpc: float | None = None
    cpm: float | None = None
    roas: float | None = None
