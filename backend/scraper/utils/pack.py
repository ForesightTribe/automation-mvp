"""Pack-size parsing — Blinkit's `unit` string → structured, comparable fields.

Blinkit stamps every product with a free-text `unit` (e.g. "225 ml", "12 x 250 ml",
"225 ml + 225 ml + 225 ml"). On its own it is unqueryable and can't be compared
across pack sizes, so this module turns it into four fields the DB stores verbatim:

    pack_raw    the source string, untouched (audit trail; a parser fix is a re-run
                of the backfill, never a re-scrape)
    pack_size   total content normalized to one base unit (675.0)
    pack_uom    the base unit that size is counted in — "ml" | "g" | "pc"
    pack_count  number of physical items in the pack (3)

Per-unit price is DERIVED, never stored: `per_unit_price(price, size, uom)`. Storing
it would double the columns and go stale against any price correction.

Grammar (validated 100% against ~290k real staged rows):

    unit  := term ( "+" term )*
    term  := [ mult ("x"|"*") ] qty uom          # "12 x 250 ml", "225 ml"

`pack_count` sums the multipliers across terms, so a 12-pack, a 3-flavour bundle and
a Buy-2-Get-1 all resolve to their true item count — a strictly better combo signal
than the product name (which misses ~13% of multipacks). See docs/per-unit-price.md.
"""
import re

from scraper.utils.search_result import is_combo_name

# Each accepted UOM token → (base unit, factor into that base). Litres fold into ml,
# kilo/milli into g, and every count-like token into "pc" so `1 ltr` and `1000 ml`
# (or `6 N` and `6 pcs`) compare directly without the reader tracking how it was
# written. Extend here, nowhere else.
_UOM: dict[str, tuple[str, float]] = {
    # volume → ml
    "ml": ("ml", 1.0), "l": ("ml", 1000.0), "lt": ("ml", 1000.0),
    "ltr": ("ml", 1000.0), "litre": ("ml", 1000.0), "liter": ("ml", 1000.0),
    # weight → g
    "g": ("g", 1.0), "gm": ("g", 1.0), "gms": ("g", 1.0),
    "gram": ("g", 1.0), "grams": ("g", 1.0),
    "kg": ("g", 1000.0), "mg": ("g", 0.001),
    # count → pc
    "pc": ("pc", 1.0), "pcs": ("pc", 1.0), "piece": ("pc", 1.0), "pieces": ("pc", 1.0),
    "n": ("pc", 1.0), "u": ("pc", 1.0), "no": ("pc", 1.0), "nos": ("pc", 1.0),
    "unit": ("pc", 1.0), "units": ("pc", 1.0), "pack": ("pc", 1.0), "packs": ("pc", 1.0),
    "sachet": ("pc", 1.0), "sachets": ("pc", 1.0),
    "tablet": ("pc", 1.0), "tablets": ("pc", 1.0),
    "capsule": ("pc", 1.0), "capsules": ("pc", 1.0),
}

# One term: optional "<mult> x" prefix, then "<qty> <uom>". Both numbers may be
# decimal ("1.2 ltr", "13.5 g"). Anchored — a term must match wholly or the whole
# unit is treated as unparseable.
_TERM = re.compile(
    r"^\s*(?:(?P<mult>\d+(?:\.\d+)?)\s*[xX*]\s*)?"
    r"(?P<qty>\d+(?:\.\d+)?)\s*(?P<uom>[a-zA-Z]+)\s*$"
)

# Display basis multiplier per family: volume/weight read as ₹ per 100 ml / 100 g (the
# Indian shelf convention, and it keeps this catalog in a ~₹6–311 band where ₹/ml
# underflows and ₹/L inflates); count items read as ₹ per piece, since per-100 is
# meaningless for them. `formatUnitPrice` in the frontend renders the matching suffix
# ("100 ml" / "100 g" / "piece") — keep the two in sync.
_BASIS: dict[str, float] = {"ml": 100.0, "g": 100.0, "pc": 1.0}


def parse_pack(raw: str | None) -> tuple[float | None, str, int | None] | None:
    """Parse a `unit` string into ``(pack_size, pack_uom, pack_count)``.

    Returns:
      * ``None`` — unparseable (a term didn't match, or an unknown UOM): store the
        raw string and leave every derived field empty.
      * ``(None, "", count)`` — a *heterogeneous* combo (e.g. "60 g + 100 ml"): the
        item count is trustworthy but there is no single denominator, so size/uom are
        empty and per-unit price stays None (honest blank over a fabricated number).
      * ``(size, uom, count)`` — a normal, comparable pack.
    """
    if not raw or not raw.strip():
        return None

    total = 0.0
    count = 0.0
    bases: set[str] = set()
    for part in raw.split("+"):
        m = _TERM.match(part)
        if not m:
            return None
        base_uom = _UOM.get(m.group("uom").lower())
        if base_uom is None:
            return None
        base, factor = base_uom
        mult = float(m.group("mult") or 1)
        qty = float(m.group("qty"))
        total += mult * qty * factor
        # Item count: for measured packs (ml/g) each term is one container, so the
        # multiplier is the item count ("12 x 250 ml" = 12 bottles). For count packs
        # the pieces ARE the items, so it's mult × qty ("6 pcs" = 6, "2 x 6 pcs" = 12).
        count += mult * qty if base == "pc" else mult
        bases.add(base)

    n_items = int(count) if count == int(count) else round(count, 3)
    if len(bases) != 1:                      # heterogeneous — count only
        return None, "", n_items
    return round(total, 3), bases.pop(), n_items


def pack_fields(raw: str | None) -> dict:
    """The four DB columns for a `unit` string, ready to store. Every writer
    (scraper, staging, loader, backfill) goes through here so the mapping lives in
    exactly one place."""
    raw = (raw or "").strip()
    parsed = parse_pack(raw)
    if parsed is None:
        return {"pack_raw": raw, "pack_size": None, "pack_uom": "", "pack_count": None}
    size, uom, count = parsed
    return {"pack_raw": raw, "pack_size": size, "pack_uom": uom, "pack_count": count}


def per_unit_price(price, size, uom: str) -> float | None:
    """Price at the display basis for its UOM family — ₹/100 ml, ₹/100 g, or
    ₹/piece. None when price or size is missing/zero, or the UOM has no basis
    (heterogeneous combos, unknown units). Never mix families in one comparison."""
    try:
        price = float(price)
        size = float(size)
    except (TypeError, ValueError):
        return None
    mult = _BASIS.get(uom)
    if mult is None or size <= 0 or price <= 0:
        return None
    return round(price / size * mult, 3)


def combo_from_pack(name: str, pack_count: int | None) -> bool:
    """Whether a product is a combo/multipack. `pack_count > 1` when the unit string
    parsed (the machine-generated, reliable signal); otherwise fall back to the
    name regex for rows whose unit is empty or unparseable."""
    if pack_count is not None:
        return pack_count > 1
    return is_combo_name(name)


# ── self-check ─────────────────────────────────────────────────────────────────
# No test suite in this repo, so the parser carries its own assertions against the
# real corpus (the awkward forms included). Run: `python -m scraper.utils.pack`.
if __name__ == "__main__":
    cases = {
        "225 ml": (225.0, "ml", 1),
        "1.2 ltr": (1200.0, "ml", 1),
        "1 ltr": (1000.0, "ml", 1),
        "13.5 g": (13.5, "g", 1),
        "60 g": (60.0, "g", 1),
        "12 x 250 ml": (3000.0, "ml", 12),
        "24 x 160 ml": (3840.0, "ml", 24),
        "225 ml + 225 ml + 225 ml": (675.0, "ml", 3),
        "60 g + 60 g": (120.0, "g", 2),
        "2 x 225 ml + 225 ml": (675.0, "ml", 3),   # Buy-2-Get-1
        "6 pcs": (6.0, "pc", 6),
        "": None,
        None: None,
        "assorted": None,
        "60 g + 100 ml": (None, "", 2),            # heterogeneous
    }
    for raw, want in cases.items():
        got = parse_pack(raw)
        assert got == want, f"parse_pack({raw!r}) = {got!r}, want {want!r}"

    # per-unit price at the display basis
    assert per_unit_price(60, 600, "ml") == 10.0          # ₹/100 ml
    assert per_unit_price(240, 3840, "ml") == 6.25        # 24 x 160 ml pack
    assert per_unit_price(52, 60, "g") == 86.667          # ₹/100 g
    assert per_unit_price(180, 6, "pc") == 30.0           # ₹/piece
    assert per_unit_price(None, 600, "ml") is None
    assert per_unit_price(60, 0, "ml") is None
    assert per_unit_price(60, 675, "") is None            # heterogeneous → no basis

    # combo resolution: pack_count wins, name is the fallback
    assert combo_from_pack("Single Bottle", 1) is False
    assert combo_from_pack("Bombay Banta Masala Soda", 12) is True     # name misses it
    assert combo_from_pack("Something Pack of 6", None) is True        # unit unparsed
    assert combo_from_pack("Plain Soda", None) is False

    print("pack.py: all self-checks passed")
