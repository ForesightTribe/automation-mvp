"""Deprecated location — session storage moved to `platform_auth.store`.

Sessions were never a scraper concern: the campaign manager and the API read them
too. They now live in the `platform_auth/` package alongside the login flows.

This module stays as a re-export so existing imports keep working. Prefer:

    from platform_auth import store            # storage
    from platform_auth import service          # login / ensure / refresh

`load_session` returns a Playwright storage_state, as it always did. For the
native credential (Firebase refresh token, seller access/refresh pair) or
ready-made API headers, use `store.load()` which returns an `AuthSession`.
"""
from platform_auth.store import load_session, save_session, session_exists

__all__ = ["load_session", "save_session", "session_exists"]
