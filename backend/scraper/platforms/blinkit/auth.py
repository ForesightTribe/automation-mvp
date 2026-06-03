from scraper.utils.browser import create_browser_context
from app.utils.logger import logger


class BlinkitAuth:
    def __init__(self, phone: str, otp_handler=None):
        self.phone = phone
        self.otp_handler = otp_handler  # callable that returns OTP string
        self.cookies = {}

    async def login(self) -> dict:
        """Returns session cookies after OTP login."""
        browser, context = await create_browser_context(headless=True)
        page = await context.new_page()
        try:
            # TODO: implement Blinkit seller login flow
            logger.info(f"Blinkit login initiated for {self.phone}")
            raise NotImplementedError("Blinkit auth flow not yet implemented")
        finally:
            await browser.close()
