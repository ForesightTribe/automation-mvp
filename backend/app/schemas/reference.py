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


class ZoneOut(BaseModel):
    zone: str
    pincode: str


class CityOut(BaseModel):
    slug: str
    name: str
    state: str
    platforms: dict[str, list[ZoneOut]]  # platform -> its zones
