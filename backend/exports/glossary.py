"""The vocabulary — one canonical wording for every term an export prints.

Two jobs:

1. **Definitions.** `TERMS` is the source the "How to read this" sheet is built
   from, worded to match docs/public-glossary.md so the doc, the dashboard and
   the workbook can't drift.
2. **Enforcement.** `LABELS` maps internal field names to the business words, and
   `check_wording` refuses to render a sheet that leaks the internal ones. In
   FMCG, *numeric distribution* means breadth — the opposite of this codebase's
   `distribution_pct` (in-stock rate) — so a sales reader would read the two
   headline metrics backwards. That is a correctness bug, not a style nit, which
   is why it raises rather than warns.
"""
from app.schemas.exports import Section, Term

# Canonical order — the glossary sheet renders in this sequence.
TERMS: dict[str, Term] = {
    "on_shelf": Term(
        term="On shelf",
        meaning="How widely the product is carried — the share of stores where it appeared at all.",
        formula="stores stocking it ÷ stores observed",
        caveat="A product missing from a store may not be carried there, or may sit past our scrape depth. From outside, the two look identical.",
    ),
    "in_stock": Term(
        term="In stock",
        meaning="Of the stores that carry the product, how many actually had it available.",
        formula="stores with stock ÷ stores stocking it",
        caveat="Being listed but empty is a replenishment problem; not being listed at all is a range problem. They are counted separately.",
    ),
    "stores_observed": Term(
        term="Stores observed",
        meaning="Distinct dark stores that answered a scrape in this date range. Every percentage is out of this number.",
        formula="count of distinct stores",
        caveat="This is stores we saw, never every store on the platform.",
    ),
    "store_tier": Term(
        term="Store tier",
        meaning="Express stores hold the 10-minute core range; hub (longtail) stores carry extended range more slowly.",
        caveat="Tier belongs to how a product is fulfilled, not to the store — one store can be express to its own area and a hub to the next.",
    ),
    "share_of_search": Term(
        term="Share of search",
        meaning="How much of a search results page your products occupy for a given term.",
        formula="your results ÷ all results on the page",
    ),
    "position": Term(
        term="Position",
        meaning="Where your product sits in search results. Position 1 is the top of the page.",
        caveat="Lower is better — a rising position number is a decline.",
    ),
    "unit_price": Term(
        term="₹ per 100 ml / 100 g",
        meaning="Price normalised by pack size, so a 250 ml bottle and a 3-pack can be compared fairly.",
        formula="price ÷ pack size",
    ),
    "discount": Term(
        term="Discount",
        meaning="How far below the listed MRP the product is selling.",
        formula="(MRP − price) ÷ MRP",
    ),
    "main_vs_combo": Term(
        term="Main vs Combo",
        meaning="Main SKUs are single units; combos are multipacks and bundles. Combos are stocked selectively, so they are reported apart.",
        caveat="This workbook shows Main SKUs unless the cover says otherwise.",
    ),
    "freshness": Term(
        term="Freshness",
        meaning="When the scrape behind these numbers last ran.",
        caveat="Public marketplace data is collected weekly, not live. Check the date on the cover before acting on it.",
    ),
    # Explorer measures where it *knocked*, not which store answered — a
    # sampled one-off run has no store-level denominator to speak of.
    "probe_location": Term(
        term="Location",
        meaning="A point we searched from. Results are what a shopper at that spot would see.",
        caveat="A location is not a store: one point can be served by several stores, and one store can serve several points. Counts here are locations searched, not shops.",
    ),
}

# Terms every public workbook explains, whichever sheets it happens to contain.
CORE = ("stores_observed", "freshness", "main_vs_combo")

# Internal field name → the words a client reads. The API keeps its field names;
# this is the only place the translation lives.
LABELS: dict[str, str] = {
    "reach_pct": "On shelf %",
    "distribution_pct": "In stock %",
    "stores_listed": "Stores stocking it",
    "stores_in_stock": "Stores with stock",
    "stores_out_of_stock": "Stores with none left",
    "stores_scraped": "Stores observed",
    "avg_price": "Average price",
    "avg_discount": "Discount %",
    "merchant_id": "Store ID",
    "merchant_type": "Store tier",
    "platform_product_id": "Product ID",
    "product_name": "Product",
    "brand_sov": "Share of search %",
    "brand_rank": "Position",
}

# Words that must never reach a client's eyes, and what to say instead.
BANNED: dict[str, str] = {
    "reach": "'On shelf'",
    "distribution": "'In stock'",
    "sov": "'Share of search'",
    "merchant": "'Store'",
}


def label(field: str) -> str:
    """The business wording for an internal field name."""
    return LABELS.get(field, field.replace("_", " ").capitalize())


def collect(*keys: str, core: tuple[str, ...] = CORE) -> list[Term]:
    """The glossary for a workbook: the requested terms plus the core ones,
    de-duplicated and returned in canonical order.

    `core` is overridable because not every workbook shares the client report's
    footing — an Explorer run measures probe locations rather than dark stores,
    and is scraped live, so "Stores observed" and "Freshness" would be wrong on
    its sheets rather than merely unused.
    """
    wanted = set(keys) | set(core)
    missing = wanted - TERMS.keys()
    if missing:
        raise KeyError(f"Unknown glossary term(s): {', '.join(sorted(missing))}")
    return [term for key, term in TERMS.items() if key in wanted]


def check_wording(section: Section) -> None:
    """Refuse to render a sheet that prints an internal metric name.

    Only the reader-facing strings are checked — titles, descriptions, KPI labels
    and column headers. Column `key`s are internal plumbing and are left alone.
    """
    texts = [("title", section.title), ("description", section.description)]
    texts += [(f"KPI '{k.label}'", k.label) for k in section.kpis]
    texts += [(f"column '{c.header}'", c.header) for c in section.columns]

    for where, text in texts:
        words = {w.strip(".,()%:").lower() for w in text.split()}
        for bad, instead in BANNED.items():
            if bad in words:
                raise ValueError(
                    f"Section '{section.key}' {where} says '{bad}' — use {instead}. "
                    f"See the clarity rules in docs/exports.md."
                )
