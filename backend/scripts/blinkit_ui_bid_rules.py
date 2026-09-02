"""READ-ONLY: fetch Blinkit's dashboard JS bundles to disk so the bid/budget validation can
be read directly.

`min_cpm_config` governs neither keyword bids (live bids of ₹51–₹402 under a "500" floor)
nor daily budgets (live budgets of ₹102–₹302). But the bundle does contain
`validateBidRange(v, {min: minBid, max: maxBid})` and `getBudgetErr({minCpm, campaign,
budget})` — so the number the client means by "Blinkit's minimum bid" is computed in the
frontend, and this is where to read how.

Downloads text; submits nothing.

    python -m scripts.blinkit_ui_bid_rules <tenant>   # → out/blinkit_js/*.js
"""
import asyncio
import pathlib
import sys

from campaign_manager.marketplaces.blinkit import client as bk

OUT = pathlib.Path("out/blinkit_js")


async def main(tenant: str) -> None:
    pw, browser, cl = await bk.setup(tenant)
    page = cl._page
    try:
        await page.goto(f"{bk.BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(6000)
        sources = await page.evaluate("""
        async () => {
            const out = {};
            for (const s of Array.from(document.querySelectorAll('script[src]'))) {
                try { out[s.src] = await (await fetch(s.src)).text(); } catch (e) {}
            }
            const extra = new Set();
            for (const body of Object.values(out)) {
                for (const m of body.matchAll(/["'`]([\\w.\\-\\/]*(?:assets|static)\\/[\\w.\\-\\/]+\\.js)["'`]/g)) {
                    extra.add(new URL(m[1], location.origin).href);
                }
            }
            for (const src of extra) {
                if (out[src]) continue;
                try { out[src] = await (await fetch(src)).text(); } catch (e) {}
            }
            return out;
        }""")
    finally:
        await browser.close()
        await pw.stop()

    OUT.mkdir(parents=True, exist_ok=True)
    for src, body in sources.items():
        name = src.rsplit("/", 1)[-1] or "index.js"
        (OUT / name).write_text(body, encoding="utf-8")
        print(f"{len(body):>10,}  {name}")


asyncio.run(main(sys.argv[1]))
