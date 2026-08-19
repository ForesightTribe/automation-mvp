"""Platform authentication — logging in to marketplace dashboards.

NOT app-user auth. `app/routes/auth.py` handles humans logging into Foresight
(JWT); this package handles Foresight logging into Blinkit, Zepto and friends.
The names are close enough that keeping them apart matters — see the glossary in
docs/jobs.md for the other overloaded terms.

Layout, and why:

    types.py                 the Authenticator contract + AuthSession
    registry.py              slug -> Authenticator      <- the extension point
    service.py               login / ensure / refresh   <- what callers use
    store.py                 encrypted persistence
    errors.py                typed failures
    inbox/                   where the secret comes from (imap | manual)
    marketplaces/<mp>/<dash>.py   one module per dashboard

Two levels under marketplaces/ because a marketplace is not a login: Blinkit
alone has two unrelated ones (Firebase magic link for brands.blinkit.com, REST
OTP for partnersbiz.com). Mirrors campaign_manager/marketplaces/.

Adding a marketplace: a folder here, one registry entry. Nothing above changes.
"""
