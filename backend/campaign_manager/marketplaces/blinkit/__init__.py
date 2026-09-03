"""Blinkit marketplace adapter package.

Self-contained since 2026-07-30: the engine (`client.py` + `live_position.py`) was
copied out of the legacy `ad_campaigns/` into this package. That package was deleted on
2026-09-03, so this is now the only Blinkit ad client in the repo. There is no second copy
to drift out of sync with, and a duplicated payload builder is exactly how a bug in one of
them hides.
"""
