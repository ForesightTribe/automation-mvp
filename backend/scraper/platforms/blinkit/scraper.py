import httpx
from typing import List
from scraper.platforms.base import BasePlatformScraper
from scraper.platforms.blinkit.auth import BlinkitAuth
from scraper.platforms.blinkit.parser import parse_products, parse_sales, parse_inventory, parse_ads
from scraper.normalizer.schema import NormalizedProduct, NormalizedSales, NormalizedInventory, NormalizedAd
from scraper.utils.retry import retry
from app.utils.logger import logger

BLINKIT_API_BASE = "https://seller.blinkit.com/api"  # placeholder — reverse engineer actual base


class BlinkitScraper(BasePlatformScraper):
    def _platform_name(self) -> str:
        return "blinkit"

    async def login(self) -> bool:
        auth = BlinkitAuth(phone=self.credentials["phone"])
        self.session_cookies = await auth.login()
        return True

    @retry(max_attempts=3, delay=2.0)
    async def fetch_products(self) -> List[NormalizedProduct]:
        async with httpx.AsyncClient(cookies=self.session_cookies) as client:
            # TODO: replace with actual Blinkit products endpoint
            response = await client.get(f"{BLINKIT_API_BASE}/products")
            response.raise_for_status()
            return parse_products(response.json(), self.tenant_id)

    @retry(max_attempts=3, delay=2.0)
    async def fetch_sales(self, days: int = 30) -> List[NormalizedSales]:
        async with httpx.AsyncClient(cookies=self.session_cookies) as client:
            response = await client.get(f"{BLINKIT_API_BASE}/sales", params={"days": days})
            response.raise_for_status()
            return parse_sales(response.json(), self.tenant_id)

    @retry(max_attempts=3, delay=2.0)
    async def fetch_inventory(self) -> List[NormalizedInventory]:
        async with httpx.AsyncClient(cookies=self.session_cookies) as client:
            response = await client.get(f"{BLINKIT_API_BASE}/inventory")
            response.raise_for_status()
            return parse_inventory(response.json(), self.tenant_id)

    @retry(max_attempts=3, delay=2.0)
    async def fetch_ads(self) -> List[NormalizedAd]:
        async with httpx.AsyncClient(cookies=self.session_cookies) as client:
            response = await client.get(f"{BLINKIT_API_BASE}/ads")
            response.raise_for_status()
            return parse_ads(response.json(), self.tenant_id)
