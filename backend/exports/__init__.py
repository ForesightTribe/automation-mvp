"""Exports — stored Foresight data → a client-ready Excel workbook.

`workbook.write_workbook(report, path)` is the only renderer; `theme.py` holds
every visual decision. Sections build typed `Report` objects (Phase 2+), so the
same output feeds a future JSON endpoint without touching this layer.

See docs/exports.md.
"""
from exports.workbook import write_workbook

__all__ = ["write_workbook"]
