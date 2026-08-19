"""Platform slug -> Authenticator. The sole extension point of this package.

Adding a marketplace is: a folder under `marketplaces/`, a rule in
`mail_rules.py`, then one entry here. Nothing above this layer changes — the CLI,
the job runner and the scrapers all go through `service.py`, which only ever sees
`Authenticator`.

Registering a platform as `wired=False` is deliberate, and mirrors
scraper/public/providers.py: selecting Zepto before its authenticator exists
fails fast with a clear message instead of silently doing something else.

Slugs match `platform_sessions.platform` exactly — `blinkit` and `blinkit_seller`
are the values already in the table, so nothing needs migrating.
"""
from platform_auth.errors import PlatformNotWired, UnknownPlatform
from platform_auth.marketplaces.blinkit import marketing as blinkit_marketing
from platform_auth.marketplaces.blinkit import seller as blinkit_seller
from platform_auth.types import Authenticator, SecretKind

AUTHENTICATORS: dict[str, Authenticator] = {
    "blinkit": Authenticator(
        slug="blinkit",
        name="Blinkit Marketing (brands.blinkit.com)",
        marketplace="blinkit",
        secret_kind=SecretKind.MAGIC_LINK,
        needs_password=False,          # magic link — possession of the inbox IS the credential
        wired=True,
        start_login=blinkit_marketing.start_login,
        complete_login=blinkit_marketing.complete_login,
        probe=blinkit_marketing.probe,
        refresh=blinkit_marketing.refresh,
        refreshable=True,
    ),
    "blinkit_seller": Authenticator(
        slug="blinkit_seller",
        name="Blinkit Seller (partnersbiz.com)",
        marketplace="blinkit",
        secret_kind=SecretKind.OTP,
        needs_password=False,          # OTP only
        wired=True,
        start_login=blinkit_seller.start_login,
        complete_login=blinkit_seller.complete_login,
        probe=blinkit_seller.probe,
        refresh=blinkit_seller.refresh,
        refreshable=True,
    ),
    # Placeholders — see docs/zepto.md. Listed so `cli auth platforms` shows the
    # roadmap and so selecting one fails with a real message.
    "zepto": Authenticator(
        slug="zepto",
        name="Zepto Brand Console",
        marketplace="zepto",
        secret_kind=SecretKind.OTP,
        needs_password=True,           # email + password, unlike either Blinkit dashboard
        wired=False,
    ),
    "instamart": Authenticator(
        slug="instamart",
        name="Swiggy Instamart Seller",
        marketplace="instamart",
        secret_kind=SecretKind.OTP,
        needs_password=False,          # unconfirmed — revisit when wiring it up
        wired=False,
    ),
}


def get(slug: str) -> Authenticator:
    """Look up an authenticator, or fail with a message that names the options."""
    auth = AUTHENTICATORS.get(slug)
    if auth is None:
        raise UnknownPlatform(slug, list(AUTHENTICATORS))
    if not auth.wired:
        raise PlatformNotWired(slug)
    return auth


def describe(slug: str) -> Authenticator | None:
    """Look up without the wired check — for listings and status output."""
    return AUTHENTICATORS.get(slug)


def wired_slugs() -> list[str]:
    return sorted(s for s, a in AUTHENTICATORS.items() if a.wired)


def for_marketplace(marketplace: str) -> list[Authenticator]:
    """Every dashboard of one marketplace — Blinkit already has two."""
    return [a for a in AUTHENTICATORS.values() if a.marketplace == marketplace]
