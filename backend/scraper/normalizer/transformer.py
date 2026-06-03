from scraper.normalizer.schema import NormalizedProduct, NormalizedSales, NormalizedInventory, NormalizedAd


# Each platform's parser.py maps raw API responses to these normalized types.
# This module holds any shared transformation helpers used across platforms.

def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
