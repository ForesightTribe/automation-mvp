"""Blinkit's campaign-status vocabulary → the engines' canonical set. PURE.

Separate from `adapter.py` because the API process needs it too (to tell the UI a
campaign's canonical state), and Blinkit's adapter imports Playwright, which the API must
never load. Nothing here imports anything.
"""

FROM_BLINKIT = {
    "ACTIVE": "running",
    "STOPPED": "paused",        # user-stopped — resumable
    "ON_HOLD": "held",          # Blinkit-imposed — never ours to clear
    "COMPLETED": "ended",       # terminal
    "DRAFT": "draft",           # never launched
    # TRANSIENT, and it bit us in production on 2026-08-08: for a minute or two after a
    # RESTART, Blinkit reports the campaign as SCHEDULED before settling to ACTIVE. It is
    # live (or imminently so), not stopped — so it maps to `running`: we may set its budget
    # and we may stop it. Treating it as unknown made the engine skip a window-end stop and
    # leave the campaign spending. Too short-lived to appear in the scraped status table,
    # which is why the first five values looked like the whole vocabulary.
    "SCHEDULED": "running",
}


def canonical(blinkit_status: str | None) -> str | None:
    """Blinkit's status → ours. An unmapped value returns as-is so the guardrail can
    refuse it by name rather than silently coercing it to something writable."""
    if not blinkit_status:
        return None
    return FROM_BLINKIT.get(blinkit_status.strip().upper(), blinkit_status)
