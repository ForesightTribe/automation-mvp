"""Instamart Supply Portal (partner.instamart.in/im-vendor) — a SEPARATE
portal/API family from everything else under `dashboard_data/seller/`.

    seller/  -> partner.instamart.in/instamart/...   brand-portal-service-http.swiggy.com   (ads/sales, WASM-signed)
    supply/  -> partner.instamart.in/im-vendor/...    picker.swiggy.com                       (purchase orders)

Confirmed live 2026-09-25 via DevTools capture (not yet driven by our own
code): three POST calls, one header `abacus-token: <JWT>`. Decoded claims on
the captured token: `{"sub": "11214", "email": "ecom@brikoven.com",
"user_pool": "USER_POOL_BRAND", "session_id": ..., "exp": ...}` — SAME email
and user_pool as the seller/ Brand Portal session, which strongly suggests
(not yet proven) this token can be minted from the same base login rather
than needing its own OTP flow. That is the open question session.py must
answer before this module can run unattended: does navigating the already-
logged-in Brand Portal page to /im-vendor/... populate an abacus-token the
way the ads SPA populates __IM_ADS_ACCESS_TOKEN__, or does im-vendor require
its own separate login?

CONFIRMED LIVE 2026-09-25 (session.py, fetch.py): no WASM signature needed —
a plain `abacus-token` bearer header is enough, and it works from a PLAIN
httpx call with the browser closed. `picker.swiggy.com` does not enforce the
transport-fingerprint wall `brand-portal-service-http.swiggy.com` does. See
session.py's docstring for how the token is obtained.

Real request bodies (captured live, same day):
    purchaseMetrics        {"mask": "po_metrics",
                             "filters": {"supplier_id": "", "brand_company_id": <id>},
                             "interval": {"start_time": <epoch_s>, "end_time": <epoch_s>}}
    searchPurchaseOrder     {"filters": {"brand_company_id": <id>, "selling_party.id": ""},
                             "pagination": {"page_number": <n>, "size": <n>},
                             "sort": [{"sort_by": "pending_qty", "sort_order": "DESC"}],
                             "query": {"id": "", "ship_to_party.name": ""}}
    listPurchaseOrderLines  {"filters": {"purchase_order_id": <id>}}
No throttling observed on any of these three (unlike the Brand Portal's near-
constant 403s) across the calls made during investigation — treat that as
provisional, not a documented guarantee, and fetch.py still backs off on a
429/403 rather than assuming it can never happen.
"""
PORTAL = "https://partner.instamart.in"
DATA = "https://picker.swiggy.com"

# The Brand Portal login is shared; this is the in-app route that (we expect)
# exchanges that session for an abacus-token. Unverified — see module docstring.
VENDOR_PATH = "/im-vendor/po-dashboard"

# ── Data calls ───────────────────────────────────────────────────────────────
PURCHASE_METRICS = "/api/v1/purchaseMetrics"
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

PAGE_SIZE = 50  # captured requests used size=10 (portal's UI page); we ask for more per call to cut round trips — unverified upper bound.
