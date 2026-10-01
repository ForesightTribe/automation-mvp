"""Action Center insights — one typed, ranked item per thing worth acting on.

An insight carries its own evidence so the UI can answer "why am I seeing this?".
`impact` is OPTIONAL and deliberately so: a rupee figure is attached only where the
data supports one. Visibility and pricing changes are reported with their real
units (percentage points, counts) rather than converted into revenue, because no
validated elasticity or attribution model exists to make that conversion honest.
"""
from typing import Literal

from pydantic import BaseModel

InsightType = Literal["issue", "opportunity", "change", "win"]
Severity = Literal["critical", "high", "medium", "low"]
ImpactType = Literal[
    "revenue_at_risk",
    "inefficient_spend",
    "fill_loss",
    "visibility",
    "availability",
    "pricing",
]
Unit = Literal["INR", "percent", "percentage_points", "count"]
Confidence = Literal["high", "medium", "low"]


class Evidence(BaseModel):
    """One measurement behind an insight. `current`/`baseline` are set where the
    insight is a CHANGE; `value` alone where it is a level or a count."""

    metric: str
    value: float | None = None
    current: float | None = None
    baseline: float | None = None
    change: float | None = None
    unit: Unit | None = None
    period: str | None = None


class Where(BaseModel):
    """What the insight touches. Every field optional — an ads insight names
    campaigns, an availability one names stores and SKUs."""

    platform: str | None = None
    cities: list[str] | None = None
    stores: int | None = None
    skus: int | None = None
    keywords: int | None = None
    campaigns: int | None = None


class Impact(BaseModel):
    """The size of the thing. `value` is None when the evidence does not support a
    number — that is a valid, deliberate state, not missing data."""

    type: ImpactType
    value: float | None = None
    unit: Unit | None = None
    confidence: Confidence | None = None


class InsightItem(BaseModel):
    """One of the things an insight is about — a SKU, a campaign, a keyword.

    Carried with the insight so the drawer can answer "which ones?" without
    sending the reader to another page to find out.
    """

    label: str
    sublabel: str | None = None  # category · pack, for a SKU
    value: float | None = None
    unit: Unit | None = None
    # A ratio the row is really about ("46 of 1,782 dark stores"), kept as two
    # numbers so the UI can show the share as well as the count.
    count: int | None = None
    total: int | None = None
    # A second ratio the row is also about, shown as its own column.
    secondary_count: int | None = None
    secondary_total: int | None = None
    note: str | None = None
    image: str | None = None  # product shot from the public scrape, when matched


class Insight(BaseModel):
    id: str
    type: InsightType
    severity: Severity
    title: str
    what: str
    where: Where = Where()
    impact: Impact | None = None
    evidence: list[Evidence] = []
    items: list[InsightItem] = []  # the rows behind the headline
    item_label: str | None = None  # header for the items' metric column
    item_secondary_label: str | None = None  # header for the second ratio
    source: str | None = None  # which feed the rows came from
    method: str | None = None  # one line on how the rows were selected
    href: str
    cta: str
    as_of: str | None = None  # the data's own date, at its real granularity
