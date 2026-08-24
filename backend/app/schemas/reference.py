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


class ZoneOut(BaseModel):
    zone: str
    pincode: str


class CityOut(BaseModel):
    slug: str
    name: str
    state: str
    platforms: dict[str, list[ZoneOut]]  # platform -> its zones
