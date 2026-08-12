"""Export schemas — the export's data contracts, both directions.

`ReportSpec` is the *input*: which client, which window, which sheets. The CLI
parses argv into it today; a future `GET /clients/{id}/exports/public` validates
its query into the same model.

`Report` is the *output*, and is renderer-agnostic: sections declare *what a
column is* (a count, a percentage, money) and the Excel writer decides how it
looks. Nothing here knows about openpyxl, so the same `Report` can feed a JSON
endpoint later.
"""
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# What a column *is*. Drives number format, alignment and width bounds — see
# `exports/theme.py`. Sheet authors pick a type; they never pick a format.
ColumnType = Literal["text", "id", "count", "pct", "money", "money_fine", "rating", "date"]

# How a column is emphasised. Deliberately narrow: data bars for magnitudes,
# two-colour scales for good/bad percentages, and `heat` (the loud three-colour
# scale) reserved for grids whose whole job is spotting weak cells.
Emphasis = Literal["none", "bar", "good_high", "good_low", "heat"]

# No "raw" group: raw rows are CSV via `cli export raw`, never a sheet.
SectionGroup = Literal["cover", "insight"]
Kind = Literal["main", "combo", "all"]


class ReportSpec(BaseModel):
    """One export run. The CLI parses argv into this; a future endpoint validates
    its query string into the same model."""

    tenant_id: uuid.UUID
    start: date                          # inclusive, the dates the user SELECTED
    end: date                            # inclusive — never "N days from now"
    marketplace: str | None = None       # None = every marketplace with data
    cities: list[str] = Field(default_factory=list)   # empty = every covered city
    kind: Kind = "main"                  # combos are stocked selectively, so default main

    group: str = "public"                # which family of sections to build
    sections: list[str] = Field(default_factory=list)  # empty = the whole group
    label: str = ""                      # optional human label for the run

    # No raw-data option by design: the underlying rows are hundreds of thousands
    # per window, so they ship through `cli export raw` (CSV, on demand) rather
    # than riding along in a report meant for a download button.

    @model_validator(mode="after")
    def _check(self):
        if self.end < self.start:
            raise ValueError("`end` is before `start`.")
        # The read services filter one city at a time. Silently widening a
        # two-city request to "all cities" would return more data than was asked
        # for and quietly overstate every denominator — so refuse instead.
        if len(self.cities) > 1:
            raise ValueError(
                "One city at a time for now — multi-city sections are not built yet."
            )
        return self

    @property
    def city(self) -> str | None:
        return self.cities[0] if self.cities else None


class Column(BaseModel):
    """One column of a section's table."""

    key: str
    header: str
    type: ColumnType = "text"
    help: str = ""                 # hover comment on the header + a glossary row
    emphasis: Emphasis = "none"
    width: int | None = None       # override the computed width; rarely needed
    wrap: bool = False             # long free text (a note column)

    # Status chips: cell value → "good" | "warn" | "bad". Declared explicitly by
    # the section rather than guessed from the text, so a wording change can't
    # silently turn a red cell green.
    chips: dict[str, str] = Field(default_factory=dict)


class Kpi(BaseModel):
    """A headline number. `detail` carries the counts behind a percentage —
    clarity rule #2 says a bare % never ships alone."""

    label: str
    value: Any = None
    type: ColumnType = "count"
    detail: str = ""               # e.g. "4,312 of 5,090 stores"
    help: str = ""


class Section(BaseModel):
    """One sheet: a KPI block, a table, or both."""

    key: str
    title: str
    description: str = ""          # one plain-English line, printed under the title
    context: str = ""              # "1-7 Aug 2026 · Main SKUs · 5,090 stores observed"
    group: SectionGroup = "insight"

    kpis: list[Kpi] = Field(default_factory=list)
    columns: list[Column] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    total_row: dict[str, Any] | None = None      # rendered last, bold, top-ruled
    notes: list[str] = Field(default_factory=list)   # caveats, printed under the table

    highlight_key: str | None = None   # truthy row key → own-brand tint
    freeze_label_col: bool = True      # keep column A visible when scrolling right

    # A long sheet: skip per-cell banding, borders and conditional formatting.
    # Purely a rendering-cost switch — painting every cell of a 50k-row sheet
    # costs more than the data and bloats the file. Not a "raw data" concept:
    # raw data is CSV via `cli export raw`.
    dense: bool = False


class Term(BaseModel):
    """One glossary entry. Sourced from docs/public-glossary.md so the doc, the UI
    and the workbook can't drift."""

    term: str
    meaning: str
    formula: str = ""
    caveat: str = ""


class MetaItem(BaseModel):
    """A label/value pair on the cover sheet."""

    label: str
    value: Any = None
    note: str = ""


class Report(BaseModel):
    """A whole workbook, before it is rendered."""

    title: str
    subtitle: str = ""
    meta: list[MetaItem] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    glossary: list[Term] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)
    filename_stem: str = "report"
