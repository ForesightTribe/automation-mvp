from pydantic import BaseModel


class InstamartCampaignShare(BaseModel):
    """One campaign's contribution to a product/keyword's total. Empty only
    when no campaign-level data has been scraped yet for that row's date
    range (see instamart/dashboard_data/seller/scraper.py)."""

    campaign_id: str
    campaign_name: str | None = None
    spend: float
    sales: float
    impressions: int


class InstamartBudgetSplitRow(BaseModel):
    """Spend and recomputed RoAS for one Instamart campaign type, LIFETIME
    (see instamart_ads.budget_split's docstring for why there's no windowed
    version). Same field names as `ads.BudgetSplitRow` / `ZeptoBudgetSplitRow`
    so the frontend donut can render any of the three without branching —
    but its own model, so neither of theirs needs to change to accommodate
    a third marketplace. `campaign_type` here is ITEM / BANNER / SEARCH AUTO
    SUGGEST / COLLECTION ADS, against Blinkit's PRODUCT_LISTING / ... and
    Zepto's PLA / Display.
    """

    campaign_type: str | None
    budget_consumed: float
    ad_sales: float
    roas: float


class InstamartProductRow(BaseModel):
    """One advertised product, summed over the window, account-wide — the
    same product can run under more than one campaign, so `spend`/etc. here
    are the TOTAL across all of them. `campaigns` breaks that total down by
    campaign (see InstamartCampaignShare). Same field names as
    `ZeptoProductRow` so the frontend card can render either without
    branching, but its own model: Instamart has no product_category to
    offer, and units_sold is always 0 (Instamart's ad data never reports a
    unit count anywhere). `image_link` is resolved from
    `POST /api/v1/products/batch`, a full CDN url — see
    instamart_product_catalog / instamart/dashboard_data/seller/scraper.py."""

    product_variant_id: str
    product_name: str | None = None
    image_link: str | None = None

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

    campaigns: list[InstamartCampaignShare] = []


class InstamartCampaignKeywordRow(BaseModel):
    """Top keyword for ONE campaign — the Campaign insights drawer's "Top
    keywords by spend" section. No `most_viewed_position`: Instamart's
    keyword API never reports a ranked position anywhere (unlike Blinkit's
    most_viewed_position), so there is nothing honest to put there."""

    keyword: str
    spend: float
    sales: float
    impressions: int
    roas: float | None = None


class InstamartKeywordRow(BaseModel):
    """One keyword, summed over the window, account-wide — like Zepto's
    keyword table, the same keyword can be bid by more than one campaign, so
    this sums across all of them. `campaigns` breaks that down per campaign."""

    keyword: str

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

    campaigns: list[InstamartCampaignShare] = []
