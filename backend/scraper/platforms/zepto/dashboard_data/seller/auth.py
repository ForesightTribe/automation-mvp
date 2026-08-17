import asyncio
from playwright.async_api import async_playwright
from scraper.platforms.zepto.dashboard_data.seller import selectors as sel
from scraper.utils.browser import create_browser_context
from app.utils.logger import logger


async def login(email: str, password: str) -> dict:
    """
    Opens a browser, navigates to the Zepto seller panel, enters email + password,
    prompts the user to enter the OTP sent to their email, then captures and
    returns the session state.

    Mirrors blinkit/dashboard_data/seller/auth.py's flow, with one extra step —
    Zepto's login asks for a password before the OTP; Blinkit's doesn't. Password
    is only ever used here, in memory, to fill the login form — never logged,
    never returned, never persisted alongside the saved session.
    """
    async with async_playwright() as p:
        browser, context = await create_browser_context(p, headless=False)
        page = await context.new_page()
        try:
            logger.info(f"Navigating to {sel.LOGIN_URL}...")
            await page.goto(sel.LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)

            await page.wait_for_selector(sel.LOGIN_EMAIL_INPUT, timeout=10_000)
            await page.fill(sel.LOGIN_EMAIL_INPUT, email)
            logger.info(f"Email entered: {email}")

            await page.wait_for_selector(sel.LOGIN_PASSWORD_INPUT, timeout=10_000)
            await page.fill(sel.LOGIN_PASSWORD_INPUT, password)
            logger.info("Password entered")

            await page.wait_for_selector(sel.LOGIN_SUBMIT_PASSWORD_BUTTON, timeout=10_000)
            await page.click(sel.LOGIN_SUBMIT_PASSWORD_BUTTON)
            logger.info("Credentials submitted, awaiting OTP screen")

            await page.wait_for_selector(sel.LOGIN_OTP_INPUT, timeout=30_000)
            logger.info("OTP screen visible")

            loop = asyncio.get_event_loop()
            otp = await loop.run_in_executor(
                None, lambda: input("Enter the 4-digit OTP from your email: ")
            )
            otp = otp.strip()

            # Single field, unlike Blinkit's per-digit boxes — fill directly.
            await page.fill(sel.LOGIN_OTP_INPUT, otp)

            await page.wait_for_selector(sel.LOGIN_SUBMIT_OTP_BUTTON, timeout=10_000)
            await page.click(sel.LOGIN_SUBMIT_OTP_BUTTON)
            logger.info("OTP submitted")

            # Account selection screen — appears when multiple companies are linked to the email
            try:
                await page.wait_for_selector(sel.LOGIN_ACCOUNT_CARD, timeout=5_000)
                logger.info("Account selection screen detected — clicking first account")
                await page.click(sel.LOGIN_ACCOUNT_CARD)
            except Exception:
                logger.info("No account selection screen — proceeding directly")

            # Wait for the app dashboard to fully load — auth cookies and any client
            # state are only set after the post-login redirect completes
            logger.info("Waiting for dashboard to load...")
            try:
                await page.wait_for_url("**/vendor/dashboard/**", timeout=30_000)
            except Exception:
                logger.error(f"Stuck on: {page.url}")
                await page.screenshot(path="zepto_login_stuck.png")
                logger.error("Screenshot saved: zepto_login_stuck.png")
                raise
            await page.wait_for_load_state("networkidle", timeout=30_000)

            logger.info(f"Post-login URL: {page.url}")

            return await _capture_session(page, context)
        finally:
            await browser.close()


async def _capture_session(page, context) -> dict:
    raw_ls: dict = await page.evaluate("""() => {
        const o = {};
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            o[k] = localStorage.getItem(k);
        }
        return o;
    }""")
    logger.info(f"localStorage: {len(raw_ls)} keys")

    storage = await context.storage_state()
    logger.info(f"Cookies: {len(storage['cookies'])}")

    if raw_ls:
        ls_items = [{"name": k, "value": v} for k, v in raw_ls.items()]
        merged = False
        for origin in storage.get("origins", []):
            if sel.BASE_URL in origin.get("origin", ""):
                origin["localStorage"] = ls_items
                merged = True
                break
        if not merged:
            storage.setdefault("origins", []).append(
                {"origin": sel.BASE_URL, "localStorage": ls_items}
            )

    # Unlike Blinkit, Zepto's real session lives in a plain cookie (a JWT,
    # confirmed via live DevTools inspection — a UUID-named cookie holding an
    # `eyJ...` value), not Firebase/IndexedDB. context.storage_state() above
    # already captures it correctly, so no extra IndexedDB extraction needed.
    return storage
