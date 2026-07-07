"""
Live position checker — scrapes blinkit.com (consumer side) to get real-time
product positions for a keyword.

Location: lat/lon passed directly. Navigate to blinkit.com/?lat={lat}&lon={lon}
to set the dark store context, then search. This is identical to how the
competition scraper works — no pincode typing required.

Result strategy:
  1. Intercept blinkit's v1/layout/search API response (clean structured JSON)
  2. Fall back to DOM scraping anchored on Rs-price elements
"""
import logging
from playwright.async_api import async_playwright

log = logging.getLogger(__name__)

# Default: Bengaluru MG Road / Shivajinagar dark store
_DEFAULT_LAT = 12.9767
_DEFAULT_LON = 77.5713


async def get_live_positions(
    keyword: str,
    lat: float = _DEFAULT_LAT,
    lon: float = _DEFAULT_LON,
) -> list[dict]:
    """
    Search blinkit.com for keyword from a dark store at (lat, lon).
    Returns list: [{position, name, is_ad, pid}]
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            geolocation={"latitude": lat, "longitude": lon},
            permissions=["geolocation"],
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # ── Set dark store context via lat/lon URL param ──────────────────────
        # blinkit reads lat/lon from the URL query string on first load, which
        # selects the nearest dark store — same pattern as the competition scraper.
        try:
            await page.goto(
                f"https://blinkit.com/?lat={lat}&lon={lon}",
                wait_until="networkidle",
                timeout=20_000,
            )
            await page.wait_for_timeout(1000)
            print(f"[live_position] location set via lat={lat} lon={lon}", flush=True)
        except Exception as e:
            log.warning("[live_position] homepage load failed: %s", e)

        captured: list[dict] = []

        # ── Intercept blinkit's search API ────────────────────────────────────
        async def _on_response(response):
            if "blinkit.com/v1/layout/search" not in response.url:
                return
            try:
                data = await response.json()
                snippets = (data.get("response") or {}).get("snippets") or []
                if not snippets:
                    return

                batch: list[dict] = []
                for sn in snippets:
                    if not isinstance(sn, dict):
                        continue
                    d = sn.get("data") or {}
                    if not isinstance(d, dict):
                        continue

                    # blinkit wraps product name as {"text": "Product Name"}
                    name_raw = d.get("name") or {}
                    name = (
                        (name_raw.get("text") if isinstance(name_raw, dict) else str(name_raw)) or ""
                    ).strip()
                    if not name or len(name) <= 2:
                        continue

                    # PID: data.identity.id
                    pid = str((d.get("identity") or {}).get("id") or "").strip()

                    # is_sponsored: non-empty ads_campaign_id means a sponsored slot
                    common = (sn.get("tracking") or {}).get("common_attributes") or {}
                    ads_campaign_id = str(common.get("ads_campaign_id") or "").strip()
                    is_ad = bool(ads_campaign_id and ads_campaign_id not in ("0", "null", "None"))

                    batch.append({
                        "position": len(captured) + len(batch) + 1,
                        "name": name[:100],
                        "is_ad": is_ad,
                        "pid": pid,
                    })

                if batch:
                    captured.extend(batch)
                    print(
                        f"[live_position] API page +{len(batch)} products "
                        f"(total={len(captured)}) {response.url[:80]}",
                        flush=True,
                    )
                    for p in batch[:3]:
                        print(
                            f"  #{p['position']} [{'Ad' if p['is_ad'] else 'organic'}] "
                            f"{p['name']} pid={p['pid']}",
                            flush=True,
                        )

            except Exception as e:
                print(f"[live_position] parse ERROR url={response.url[:80]} err={e}", flush=True)

        page.on("response", _on_response)

        try:
            await page.goto(
                f"https://blinkit.com/s/?q={keyword}",
                wait_until="networkidle",
                timeout=35_000,
            )
            await page.wait_for_timeout(3000)
        finally:
            page.remove_listener("response", _on_response)

        if captured:
            print(
                f"[live_position] returning {len(captured)} products from API intercept",
                flush=True,
            )
            await context.close()
            await browser.close()
            return captured

        # ── DOM fallback — when API intercept returns nothing ─────────────────
        print("[live_position] API intercept empty — falling back to DOM scraping", flush=True)

        try:
            await page.evaluate("window.scrollTo(0, 2000)")
            await page.wait_for_timeout(1500)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(800)
        except Exception:
            pass

        try:
            results = await page.evaluate(r"""() => {
                const out = [];
                const seen = new WeakSet();

                const priceEls = Array.from(document.querySelectorAll('*')).filter(el =>
                    el.children.length === 0 && /^₹\s*\d/.test(el.textContent.trim())
                );

                const rawCards = [];
                for (const priceEl of priceEls) {
                    let el = priceEl.parentElement;
                    for (let i = 0; i < 14; i++) {
                        if (!el) break;
                        const r = el.getBoundingClientRect();
                        if (r.width > 400) break;
                        if (r.width >= 100 && r.height >= 80 && el.querySelector('img')) {
                            if (!seen.has(el)) { seen.add(el); rawCards.push({ el, top: r.top, left: r.left }); }
                            break;
                        }
                        el = el.parentElement;
                    }
                }

                rawCards.sort((a, b) => {
                    const rowA = Math.floor(a.top / 50);
                    const rowB = Math.floor(b.top / 50);
                    return rowA !== rowB ? rowA - rowB : a.left - b.left;
                });

                for (const { el: card } of rawCards) {
                    const leaves = Array.from(card.querySelectorAll('*')).filter(leaf =>
                        leaf.children.length === 0 &&
                        leaf.textContent.trim().length > 4 &&
                        leaf.textContent.trim().length < 150 &&
                        !/^₹/.test(leaf.textContent.trim()) &&
                        !/^\d+\s*(ml|g\b|kg|L\b|ltr|liter|pack|pcs|MINS?)/i.test(leaf.textContent.trim()) &&
                        !/^\d+(\.\d+)?$/.test(leaf.textContent.trim()) &&
                        !['Add', 'ADD', '+', 'SAVE'].includes(leaf.textContent.trim()) &&
                        !/^(\d+%?\s*(off|OFF)|showing results|blinkit)/i.test(leaf.textContent.trim())
                    );
                    const name = leaves[0]?.textContent?.trim();
                    if (!name || name.length < 4) continue;

                    // blinkit embeds PID as card id attribute; is_ad from API only
                    out.push({
                        position: out.length + 1,
                        name: name.substring(0, 100),
                        is_ad: false,
                        pid: card.id || null,
                    });
                    if (out.length >= 40) break;
                }
                return out;
            }""")
            print(f"[live_position] DOM fallback found {len(results)} products", flush=True)
            for r in results:
                print(f"  #{r['position']} {r['name']} pid={r.get('pid')}", flush=True)
            return results
        except Exception as e:
            log.error("[live_position] DOM fallback error: %s", e)
            return []
        finally:
            await context.close()
            await browser.close()
