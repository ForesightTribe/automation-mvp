from pydantic import BaseModel, ConfigDict


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    category: str | None
    logo: str | None
    tint: str | None


class MarketplaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    color: str | None
    # Whether this marketplace has real, trusted data. The selector shows all
    # marketplaces but disables/labels the unconnected ones.
    connected: bool = False
    # "full" = public scrape + seller panel (revenue/ads/stock); "public" = public
    # scrape only. Lets the UI hide metrics a marketplace can't structurally supply
    # instead of showing them blank.
    data_scope: str = "public"
    # Whether the campaign manager can drive this marketplace (budget/bid automations,
    # start/stop). From the adapter registry, so the ads pages grey out a marketplace the
    # engines cannot act on instead of offering controls that would 404.
    automations: bool = False
    # The marketplace's published minimum daily budget (Zepto ₹500), or None when it
    # publishes none (Blinkit). Shown as a hint; the API refuses below it either way.
    min_daily_budget: float | None = None
    # Keyword-bid automations on this marketplace: None = available, else why not (Zepto,
    # for now). The wizard greys out "Keyword Automation" with this sentence.
    keyword_bidding_off: str | None = None
