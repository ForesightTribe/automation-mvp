# CLI Reference

Run from `backend/` with the virtual environment active.

---

## Auth

### Blinkit marketing (`brands.blinkit.com`) — magic link
```
python -m cli auth blinkit --tenant <tenant_id>
```
Browser opens → fill email → paste magic link from email into terminal.

### Blinkit seller (`partnersbiz.com`) — OTP
```
python -m cli auth blinkit-seller --tenant <tenant_id>
```
Browser opens → fills email → enter 6-digit OTP from email into terminal.

Used for all three seller commands: `blinkit-seller` (sales + PO) and `blinkit-scorecard`.

### Check session status
```
python -m cli auth status --tenant <tenant_id>
```

---

## Scrape

### Blinkit marketing
```
python -m cli scrape blinkit --tenant <tenant_id>
python -m cli scrape blinkit --tenant <tenant_id> --no-save   # dry run
```
Scrapes campaigns, brand collections, and visibility plans. No date range — always current state.

---

### Blinkit seller — sales + PO + SOH
```
# Daily run — scrapes all three: sales (yesterday), PO, and stock on hand
python -m cli scrape blinkit-seller --tenant <tenant_id>

# Sales only
python -m cli scrape blinkit-seller --tenant <tenant_id> --sales

# Sales with date range (historical backfill)
python -m cli scrape blinkit-seller --tenant <tenant_id> --sales --from 2026-06-01 --to 2026-06-05

# PO only
python -m cli scrape blinkit-seller --tenant <tenant_id> --po

# PO with custom rolling window (default: 90 days)
python -m cli scrape blinkit-seller --tenant <tenant_id> --po --po-days-back 60

# SOH only
python -m cli scrape blinkit-seller --tenant <tenant_id> --soh

# Dry run
python -m cli scrape blinkit-seller --tenant <tenant_id> --no-save
```

**Sales** — scrapes day-by-day over the given range (default: yesterday). Each day stored as separate documents; re-running the same date updates existing records.

**PO** — scrapes a rolling window of POs by issue date. Upserts by `po_number` so re-running updates state without duplicating. SKU details are fetched only for POs not already in the database (incremental — first run is expensive, subsequent runs fetch only new POs).

**SOH** — scrapes today's stock levels per SKU per facility. One doc per `item_id + facility_id + date`; re-running the same day updates in place.

---

### Blinkit seller — scorecard (fill rates)
```
# Standard run — fetches the most recently published week
python -m cli scrape blinkit-scorecard --tenant <tenant_id>

# Specific week — pass the Monday start date
python -m cli scrape blinkit-scorecard --tenant <tenant_id> --week 2026-06-01

# Dry run
python -m cli scrape blinkit-scorecard --tenant <tenant_id> --no-save
```

**Scorecard** — scrapes weekly fill rate metrics. Blinkit publishes each week's data on the following Monday, so the default always fetches last week's data (current Monday − 7 days). Intended to run once per week. Uses the same `blinkit_seller` session — no separate auth needed.

Saves to three collections:
- `blinkit_scorecard_weekly` — overall fill rate + per-category breakdown (1 doc per week)
- `blinkit_scorecard_facilities` — per-warehouse fill rate and potential loss
- `blinkit_scorecard_key_skus` — SKUs with the highest potential revenue loss

The `--week` date must be a Monday (`YYYY-MM-DD`). Passing a non-Monday will return empty data from Blinkit.

---

## Notes
- `.env` must have `MONGODB_URL` and `ENCRYPTION_KEY`
- Run `auth` before `scrape` for each tenant
