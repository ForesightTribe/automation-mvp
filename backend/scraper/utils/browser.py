from playwright.async_api import Browser, BrowserContext, Playwright, Route, Request
from app.utils.logger import logger

PLAYWRIGHT_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_WRITE_METHODS = {"PUT", "DELETE", "PATCH"}
_WRITE_PATTERNS = ("/create", "/update", "/delete", "/edit",
                   "/place", "/cancel", "/submit", "/order/new")


async def create_browser_context(
    playwright: Playwright,
    headless: bool = True,
    storage_state: dict | None = None,
) -> tuple[Browser, BrowserContext]:
    browser = await playwright.chromium.launch(
        headless=headless,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=_USER_AGENT,
        locale="en-IN",
        storage_state=storage_state,
    )
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return browser, context


async def write_blocker(route: Route, request: Request) -> None:
    method = request.method.upper()
    url = request.url.lower()
    if method in _WRITE_METHODS or (method == "POST" and any(p in url for p in _WRITE_PATTERNS)):
        logger.warning(f"[SAFETY] Blocked {method} → {request.url}")
        await route.abort()
    else:
        await route.continue_()
