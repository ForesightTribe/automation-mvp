from datetime import datetime, date
from scraper.normalizer.schema import NormalizedProduct, NormalizedSales, NormalizedInventory, NormalizedAd
from scraper.normalizer.transformer import safe_float, safe_int


def parse_products(raw: list, tenant_id: str) -> list[NormalizedProduct]:
    # TODO: map Blinkit product API response fields to NormalizedProduct
    return []


def parse_sales(raw: list, tenant_id: str) -> list[NormalizedSales]:
    # TODO: map Blinkit sales API response fields to NormalizedSales
    return []


def parse_inventory(raw: list, tenant_id: str) -> list[NormalizedInventory]:
    # TODO: map Blinkit inventory API response fields to NormalizedInventory
    return []


def parse_ads(raw: list, tenant_id: str) -> list[NormalizedAd]:
    # TODO: map Blinkit ads API response fields to NormalizedAd
    return []
