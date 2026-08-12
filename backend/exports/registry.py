"""The section registry — the single extension point.

Adding a sheet to any report is one `register(...)` call. Nothing else in the
system needs to know the sheet exists: the CLI's `--sections`, the workbook's
ordering and a future per-view Download button all read from here.

A builder is `async (db, spec) -> Section | None`. Returning `None` means "no
data for this window" and the sheet is dropped rather than rendered empty.
"""
from collections.abc import Awaitable, Callable

from app.schemas.exports import ReportSpec, Section

Builder = Callable[..., Awaitable[Section | None]]

# Insertion order is sheet order in the workbook, so register in reading order.
SECTIONS: dict[str, dict] = {}


def register(
    key: str,
    *,
    group: str,
    build: Builder,
    terms: tuple[str, ...] = (),
    window_scoped: bool = True,
) -> None:
    """Add a section.

    `terms` are the glossary keys this sheet's numbers rely on — they are
    collected into the workbook's "How to read this" sheet, so a sheet can never
    use a word the glossary doesn't define.

    `window_scoped=False` marks a sheet whose data ignores the selected dates (a
    trend needs history, so it is anchored to now). Such a sheet can never be the
    only thing in a workbook — see `build_report`.
    """
    if key in SECTIONS:
        raise ValueError(f"Section '{key}' is already registered.")
    SECTIONS[key] = {"key": key, "group": group, "build": build, "terms": terms,
                     "window_scoped": window_scoped}


def resolve(spec: ReportSpec) -> list[dict]:
    """The sections to build for this spec, in registry order."""
    if spec.sections:
        unknown = [k for k in spec.sections if k not in SECTIONS]
        if unknown:
            raise ValueError(
                f"Unknown section(s): {', '.join(unknown)}. "
                f"Available: {', '.join(SECTIONS) or 'none registered'}"
            )
        wanted = set(spec.sections)
        return [s for k, s in SECTIONS.items() if k in wanted]
    return [s for s in SECTIONS.values() if s["group"] == spec.group]


def groups() -> set[str]:
    return {s["group"] for s in SECTIONS.values()}
