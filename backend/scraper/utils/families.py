"""Product families — reducing a marketplace product name to the thing being sold.

Shared by the public report (`exports/sections/families.py`) and Explorer
(`scraper/public/explorer/insights.py`) so both group variants identically. A
family that differs between two of our own workbooks is worse than no family at
all.

The rules:

- Strip the brand and any wording that describes the *offer* rather than the
  product ("Buy 2 Get 1 Free", "Pack of 3", "2 x", "value pack").
- A name that still contains "+" after that strip names two different products —
  a **bundle**, which is not a variant of either and is excluded from families.
  Checking after the strip is what keeps "Buy 2 Get 1 Free" (one flavour) from
  being mistaken for one.
"""
import re

# Wording that describes the offer, not the product.
_NOISE = [
    r"\bbuy\s*\d+\s*get\s*\d+(\s*free)?\b",
    r"\bpack\s*of\s*\d+\b",
    r"\b\d+\s*x\b",
    r"\b(multi|value|saver|family|combo|party)\s*pack\b",
    r"\bcombo\b",
    r"\bfree\b",
]


def normalise(name: str, brands: list[str]) -> str:
    """A product name reduced to the thing being sold."""
    s = (name or "").lower()
    for slug in sorted(brands or [], key=len, reverse=True):      # longest first
        s = re.sub(rf"\b{re.escape(slug.replace('-', ' '))}\b", " ", s)
    for pattern in _NOISE:
        s = re.sub(pattern, " ", s)
    s = re.sub(r"\s*/\s*", "/", s)            # "Chips / Crisps" == "Chips /Crisps"
    s = re.sub(r"[\-–—]+", " - ", s)
    s = re.sub(r"\(\s*\)|\[\s*\]", " ", s)    # brackets emptied by the noise strip
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s


def is_bundle(normalised: str) -> bool:
    """True when the normalised name still joins two different products."""
    return "+" in normalised


def label(normalised: str) -> str:
    """Title-case each alphabetic run, so "chips/crisps" becomes "Chips/Crisps"
    rather than being skipped for containing a slash."""
    return re.sub(r"[a-z]+", lambda m: m.group().capitalize(), normalised)
