"""Zepto pack size -> the grammar `scraper/utils/pack.py` already speaks.

WHY THIS EXISTS
---------------
`staging.py` derives the four pack columns by calling `pack_fields(row["unit"])`,
and `pack.py`'s grammar is `"225 ml"` / `"12 x 250 ml"`. Zepto's
`formattedPacksize` reads `"1 pack (400 g)"`. Measured across 29,125 real rows,
**`pack.py` parses 2.2% of Zepto pack strings** — so pack size, per-unit price and
`is_combo` (which falls back to the name regex whenever the pack does not parse)
are all broken for Zepto.

Zepto does supply the size STRUCTURED, at 100% fill:

    productVariant.packsize        total content, already multiplied out
    productVariant.unitOfMeasure   GRAM | MILLILITRE | PIECE | LITER | ...

Verified against the arithmetic inside the free-text string:

    1 pack (50 x 20 g)   packsize 1     KILOGRAM   = 1000 g   OK
    1 pack (9 x 11.5 g)  packsize 103.5 GRAM       = 103.5 g  OK
    150 ml X 2           packsize 300   MILLILITRE = 300 ml    OK

So we rebuild a canonical string in pack.py's own grammar and the existing
pipeline works untouched — no change to `pack.py`, `staging.py` or the loader.
Coverage goes 2.2% -> ~100%.

WHY IT LIVES HERE AND NOT IN parser.py
--------------------------------------
`targeted.py` (the own-SKU scrape) calls `provider.search()` and **never calls
`parse()`** — it classifies the raw products itself. Normalising in the parser
would therefore fix the keyword scrape and silently leave `sku_snapshots` broken.
The engine emits the shared `unit` key, so the engine is where the translation
belongs, and both callers get it for free.

The multipack MULTIPLIER is the one thing the structured fields do not carry, so
it still comes from the string. `productVariant.quantity` is NOT the count — it
is stock, identical to `availableQuantity`; the same pack string shows 1, 3 and 7
on different rows.
"""
import re

from scraper.platforms.zepto.public_data import endpoints as ep

# "1 pack (50 x 20 g)" / "9 x 11.5 g" — a count immediately followed by x and a
# number. The digit must touch the x, so "150 ml X 2" cannot match here.
_MULT_LEADING = re.compile(r"(\d+(?:\.\d+)?)\s*[xX*]\s*\d")
# "150 ml X 2" / "250 g X 2" — the multiplier trails the unit instead.
_MULT_TRAILING = re.compile(r"[xX*]\s*(\d+(?:\.\d+)?)\s*$")

# Fallbacks for rows the structured fields do not cover. Zepto zeroes `packsize`
# and sets `unitOfMeasure = COMBO` on multipacks — including HOMOGENEOUS ones like
# "200 ml X 2", which are four identical tubs and have a perfectly good
# denominator. Blanking those would discard real data.
_S_TRAILING = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s*[xX*]\s*(\d+(?:\.\d+)?)\s*$")
_S_INNER_MULT = re.compile(
    r"\(\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s*\)")
_S_PAREN = re.compile(r"\(\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)")
_S_BARE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s*$")


def multiplier(raw: str) -> float:
    """Items in the pack, from the free-text string. 1 when it says nothing."""
    if not raw:
        return 1.0
    m = _MULT_LEADING.search(raw)
    if m:
        return float(m.group(1))
    m = _MULT_TRAILING.search(raw.strip())
    if m:
        return float(m.group(1))
    return 1.0


def _fmt(n: float) -> str:
    """Trim a float that is really an integer, so "500.0 g" reads as "500 g"."""
    return str(int(n)) if float(n).is_integer() else str(round(n, 3))


def _from_string(raw: str) -> str:
    """Zepto's free-text pack string -> pack.py grammar, or "" if unusable."""
    if not raw:
        return ""
    s = raw.strip()

    m = _S_TRAILING.match(s)                    # "200 ml X 2"
    if m:
        return f"{_fmt(float(m.group(3)))} x {_fmt(float(m.group(1)))} {m.group(2)}"

    m = _S_INNER_MULT.search(s)                 # "1 pack (6 x 200 ml)"
    if m:
        return f"{_fmt(float(m.group(1)))} x {_fmt(float(m.group(2)))} {m.group(3)}"

    m = _S_PAREN.search(s)                      # "1 pack (400 g)"
    if m:
        return f"{_fmt(float(m.group(1)))} {m.group(2)}"

    m = _S_BARE.match(s)                        # "200g" / "200 g"
    if m:
        return f"{_fmt(float(m.group(1)))} {m.group(2)}"

    return ""


def canonical_unit(packsize, uom: str, raw: str) -> str:
    """Structured size + free text -> a string `pack.py` can parse.

    Returns "" when there is nothing usable, in which case `pack_fields` stores
    the raw string and leaves the derived columns empty — an honest blank rather
    than a fabricated size.
    """
    uom_key = (uom or "").upper()
    mapped = ep.UOM_MAP.get(uom_key)

    total = None
    short = ""
    if mapped and mapped[0] and packsize is not None:
        short, factor = mapped
        try:
            total = float(packsize) * factor
        except (TypeError, ValueError):
            total = None

    # Structured size missing or zeroed — which Zepto does on every COMBO row.
    # Fall back to the string rather than discarding a derivable size.
    if not total or total <= 0:
        return _from_string(raw)

    mult = multiplier(raw)
    if mult > 1 and total / mult > 0:
        return f"{_fmt(mult)} x {_fmt(total / mult)} {short}"
    return f"{_fmt(total)} {short}"


def is_combo(uom: str, raw: str) -> bool:
    """Zepto's own COMBO marker, or a multipack multiplier in the string."""
    return (uom or "").upper() == ep.COMBO_UOM or multiplier(raw) > 1


# ── self-check ───────────────────────────────────────────────────────────────
# No test suite in this repo, so the normaliser carries its own assertions
# against the real corpus. Run:
#   python -m scraper.platforms.zepto.public_data.packs
if __name__ == "__main__":
    from scraper.utils.pack import parse_pack

    cases = [
        ((500, "GRAM"), "1 pack (500 g)", "500 g", (500.0, "g", 1)),
        ((1, "KILOGRAM"), "1 pack (1 kg)", "1000 g", (1000.0, "g", 1)),
        ((103.5, "GRAM"), "1 pack (9 x 11.5 g)", "9 x 11.5 g", (103.5, "g", 9)),
        ((1, "KILOGRAM"), "1 pack (50 x 20 g)", "50 x 20 g", (1000.0, "g", 50)),
        ((300, "MILLILITRE"), "150 ml X 2", "2 x 150 ml", (300.0, "ml", 2)),
        ((500, "GRAM"), "250 g X 2", "2 x 250 g", (500.0, "g", 2)),
        ((2, "LITER"), "1 pack (2 l)", "2000 ml", (2000.0, "ml", 1)),
        ((6, "PIECE"), "1 pack (6 pcs)", "6 pc", (6.0, "pc", 6)),
        ((400, "GRAM"), "1 pack (400 g or 430 g)", "400 g", (400.0, "g", 1)),
        ((200, "GRAM"), "200g", "200 g", (200.0, "g", 1)),
        # Zepto zeroes packsize and says COMBO on multipacks. A HOMOGENEOUS one
        # still has a denominator — real rows from a live cheesecake search.
        ((0, "COMBO"), "200 ml X 2", "2 x 200 ml", (400.0, "ml", 2)),
        ((0, "COMBO"), "105 ml X 5", "5 x 105 ml", (525.0, "ml", 5)),
        ((0, "COMBO"), "1 pack (5 x 40 ml)", "5 x 40 ml", (200.0, "ml", 5)),
    ]
    for (size, uom), raw_s, want_canon, want_parse in cases:
        got = canonical_unit(size, uom, raw_s)
        assert got == want_canon, f"canonical_unit({raw_s!r}) = {got!r}, want {want_canon!r}"
        assert parse_pack(got) == want_parse, \
            f"parse_pack({got!r}) = {parse_pack(got)!r}, want {want_parse!r}"

    # An undescribed combo yields nothing — an honest blank beats a fabrication.
    assert canonical_unit(0, "COMBO", "combo pack") == ""
    assert canonical_unit(None, "", "assorted") == ""

    assert multiplier("1 pack (400 g)") == 1.0
    assert multiplier("150 ml X 2") == 2.0
    assert multiplier("1 pack (50 x 20 g)") == 50.0

    assert is_combo("COMBO", "whatever") is True
    assert is_combo("GRAM", "200 ml X 2") is True
    assert is_combo("GRAM", "1 pack (400 g)") is False

    print("zepto packs.py: all self-checks passed")
