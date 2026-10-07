"""Instamart Supply Portal (partner.instamart.in/im-vendor) — a SEPARATE
portal/API family from everything else under `dashboard_data/seller/`.

    seller/  -> partner.instamart.in/instamart/...   brand-portal-service-http.swiggy.com   (ads/sales, WASM-signed)
    supply/  -> partner.instamart.in/im-vendor/...    picker.swiggy.com                       (purchase orders)

Confirmed live 2026-09-25: one header, `abacus-token: <JWT>`, minted by the
same Brand Portal login (session.py) — no separate OTP, and no WASM signature.
The token works from a PLAIN httpx call with the browser closed:
`picker.swiggy.com` does not enforce the transport-fingerprint wall
`brand-portal-service-http.swiggy.com` does.

Real request bodies (captured live, same day):
    searchPurchaseOrder     {"filters": {"brand_company_id": <id>, "selling_party.id": ""},
                             "pagination": {"page_number": <n>, "size": <n>},
                             "sort": [{"sort_by": "pending_qty", "sort_order": "DESC"}],
                             "query": {"id": "", "ship_to_party.name": ""}}
    listPurchaseOrderLines  {"filters": {"purchase_order_id": <id>}}
No throttling observed on either (unlike the Brand Portal's near-constant
403s) — provisional, not a guarantee, so scraper.py still backs off on a
429/403 rather than assuming it can never happen.
"""
PORTAL = "https://partner.instamart.in"
DATA = "https://picker.swiggy.com"

# The Brand Portal login is shared; opening this in-app route makes the vendor
# app mint its abacus-token (session.py).
VENDOR_PATH = "/im-vendor/po-dashboard"

# ── Data calls ───────────────────────────────────────────────────────────────
SEARCH_PURCHASE_ORDER = "/api/v1/searchPurchaseOrder"
LIST_PURCHASE_ORDER_LINES = "/api/v1/listPurchaseOrderLines"

# ── Bulk CSV export (the "Bulk Download" button) ───────────────────────────
# Confirmed live 2026-09-25: fully automatable, no browser click needed.
# submit -> {"status_code":0} once accepted; list's `batch_jobs[0].state`
# goes STATE_SUBMITTED -> STATE_RUNNING -> STATE_COMPLETED (took ~45s live),
# then `output_files[0].file_url` is a pre-signed S3 URL (no auth needed,
# valid ~3h) to the exact same CSV a human would download. This CSV carries
# real per-line `ReceivedQty`/`BalancedQty` that `listPurchaseOrderLines`
# cannot give once a PO closes (see InstamartPOItem's docstring).
BATCH_SUBMIT = "/api/v1/batch/submit"
BATCH_LIST = "/api/v1/batch/list"
PO_EXPORT_JOB = "VENDOR_PORTAL_GENERATE_PURCHASE_ORDER_DOCUMENTS"
