import asyncio
from playwright.async_api import async_playwright
from scraper.platforms.blinkit.dashboard_data.seller import selectors as sel
from scraper.utils.browser import create_browser_context
from app.utils.logger import logger


async def login(email: str) -> dict:
    """
    Opens a browser, navigates to partnersbiz.com, enters email to request OTP,
    prompts the user to enter the OTP, then captures and returns the session state.
    """
    async with async_playwright() as p:
        browser, context = await create_browser_context(p, headless=False)
        page = await context.new_page()
        try:
            logger.info(f"Navigating to {sel.BASE_URL}...")
            await page.goto(sel.BASE_URL, wait_until="domcontentloaded", timeout=30_000)

            await page.wait_for_selector(sel.LOGIN_EMAIL_INPUT, timeout=10_000)
            await page.fill(sel.LOGIN_EMAIL_INPUT, email)
            logger.info(f"Email entered: {email}")

            await page.wait_for_selector(sel.LOGIN_REQUEST_OTP_BUTTON, timeout=10_000)
            await page.click(sel.LOGIN_REQUEST_OTP_BUTTON)
            logger.info("OTP requested")

            await page.wait_for_selector(sel.LOGIN_OTP_INPUTS, timeout=30_000)
            logger.info("OTP screen visible")

            loop = asyncio.get_event_loop()
            otp = await loop.run_in_executor(
                None, lambda: input("Enter the 6-digit OTP from your email: ")
            )
            otp = otp.strip()

            otp_inputs = await page.query_selector_all(sel.LOGIN_OTP_INPUTS)
            for i, digit in enumerate(otp[:6]):
                if i < len(otp_inputs):
                    await otp_inputs[i].click()
                    await page.keyboard.type(digit)
                    await asyncio.sleep(0.1)

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

            # Wait for the app dashboard to fully load — auth cookies and Redux state
            # are only set after the post-login redirect completes
            logger.info("Waiting for dashboard to load...")
            await page.wait_for_url("**/app/**", timeout=30_000)
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

    # Best-effort IndexedDB capture (may be used for auth tokens)
    try:
        idb_data = await page.evaluate("""() => new Promise((resolve) => {
            const req = indexedDB.open('firebaseLocalStorageDb', 1);
            req.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains('firebaseLocalStorage'))
                    db.createObjectStore('firebaseLocalStorage', {keyPath: 'fbase_key'});
            };
            req.onsuccess = (e) => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains('firebaseLocalStorage')) { resolve([]); return; }
                const tx = db.transaction('firebaseLocalStorage', 'readonly');
                const req2 = tx.objectStore('firebaseLocalStorage').getAll();
                req2.onsuccess = () => resolve(req2.result || []);
                req2.onerror = () => resolve([]);
            };
            req.onerror = () => resolve([]);
        })""")
        logger.info(f"IndexedDB: {len(idb_data)} items")
        storage["indexedDB"] = idb_data
    except Exception as e:
        logger.warning(f"IndexedDB capture failed: {e}")
        storage["indexedDB"] = []

    return storage
