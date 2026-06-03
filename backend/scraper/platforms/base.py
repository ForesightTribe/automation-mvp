from abc import ABC, abstractmethod
from typing import List
from scraper.normalizer.schema import (
    NormalizedProduct,
    NormalizedSales,
    NormalizedInventory,
    NormalizedAd,
)


class BasePlatformScraper(ABC):
    def __init__(self, tenant_id: str, credentials: dict):
        self.tenant_id = tenant_id
        self.credentials = credentials
        self.platform = self._platform_name()

    @abstractmethod
    def _platform_name(self) -> str: ...

    @abstractmethod
    async def login(self) -> bool: ...

    @abstractmethod
    async def fetch_products(self) -> List[NormalizedProduct]: ...

    @abstractmethod
    async def fetch_sales(self, days: int = 30) -> List[NormalizedSales]: ...

    @abstractmethod
    async def fetch_inventory(self) -> List[NormalizedInventory]: ...

    @abstractmethod
    async def fetch_ads(self) -> List[NormalizedAd]: ...

    async def run_all(self) -> dict:
        await self.login()
        return {
            "products": await self.fetch_products(),
            "sales": await self.fetch_sales(),
            "inventory": await self.fetch_inventory(),
            "ads": await self.fetch_ads(),
        }
