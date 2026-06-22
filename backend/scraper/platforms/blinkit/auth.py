import asyncio
from playwright.async_api import async_playwright
from scraper.utils.browser import create_browser_context
from app.utils.logger import logger

# brands.blinkit.com login modal. The UI uses a generated "dock" design system,
# so its utility classes are volatile — match on stable text / attributes.
_LOGIN_BUTTON = 'button:has-text("Log In")'                  # opens the login modal
_EMAIL_INPUT = 'input[type="email"]'                          # modal email field
_KEEP_SIGNED_IN = 'button[role="checkbox"]'                   # "Keep me signed in" — persist Firebase session
_SUBMIT_BUTTON = 'button:has-text("Request Sign in Link")'   # sends the magic link


async def login(email: str, base_url: str) -> dict:
    """
    Opens a browser, navigates to base_url, enters email (triggers magic link
    email), then prompts the user to paste the link. Returns the 3-layer
    storage state (cookies + localStorage + Firebase IndexedDB).

    base_url: the dashboard root, e.g. "https://brands.blinkit.com"
    """
    async with async_playwright() as p:
        browser, context = await create_browser_context(p, headless=False)
        page = await context.new_page()
        try:
            logger.info(f"Navigating to {base_url}...")
            await page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)

            try:
                # Click the "Log In" button to open the modal first
                await page.wait_for_selector(_LOGIN_BUTTON, timeout=10_000)
                await page.click(_LOGIN_BUTTON)
                # Fill email in the modal
                await page.wait_for_selector(_EMAIL_INPUT, timeout=10_000)
                await page.fill(_EMAIL_INPUT, email)
                # Keep the session persistent so the Firebase refresh token survives.
                try:
                    await page.click(_KEEP_SIGNED_IN, timeout=3_000)
                except Exception:
                    logger.warning("'Keep me signed in' checkbox not found — continuing without it.")
                # Request the magic link
                await page.click(_SUBMIT_BUTTON)
                logger.info(f"Email submitted: {email}")
            except Exception:
                logger.warning(
                    "Could not auto-fill email — login page structure may have changed. "
                    "Update selectors in blinkit/auth.py."
                )

            # Browser is open — user checks email for the magic link
            loop = asyncio.get_event_loop()
            magic_link = await loop.run_in_executor(
                None, lambda: input("Check your email and paste the magic link: ")
            )

            logger.info("Navigating to magic link...")
            await page.goto(magic_link.strip(), wait_until="networkidle", timeout=45_000)
            await asyncio.sleep(2)

            if "/diy/" not in page.url:
                logger.warning(f"Expected /diy/ after magic link, landed on: {page.url}")

            return await _capture_session(page, context, base_url)
        finally:
            await browser.close()


async def _capture_session(page, context, base_url: str) -> dict:
    # 1. Read localStorage directly — more reliable than storage_state()
    raw_ls: dict = await page.evaluate("""() => {
        const o = {};
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            o[k] = localStorage.getItem(k);
        }
        return o;
    }""")
    logger.info(f"localStorage: {len(raw_ls)} keys")

    # 2. Get cookies + Playwright-tracked localStorage
    storage = await context.storage_state()
    logger.info(f"Cookies: {len(storage['cookies'])}")

    # 3. Merge our direct localStorage read into storage_state
    if raw_ls:
        ls_items = [{"name": k, "value": v} for k, v in raw_ls.items()]
        merged = False
        for origin in storage.get("origins", []):
            if base_url in origin.get("origin", ""):
                origin["localStorage"] = ls_items
                merged = True
                break
        if not merged:
            storage.setdefault("origins", []).append(
                {"origin": base_url, "localStorage": ls_items}
            )

    # 4. Capture Firebase IndexedDB — holds the refresh token.
    #    Firebase JS SDK v9+ stores auth state here, not in localStorage.
    #    Without this, the session expires after the 1-hour JWT lifetime.
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
        logger.info(f"IndexedDB: {len(idb_data)} Firebase items")
        storage["indexedDB"] = idb_data
    except Exception as e:
        logger.warning(f"IndexedDB capture failed: {e}")
        storage["indexedDB"] = []

    return storage
