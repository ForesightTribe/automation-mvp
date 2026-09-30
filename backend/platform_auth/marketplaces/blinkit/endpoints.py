"""Blinkit auth endpoints and constants.

All URLs and static keys for Blinkit logins live here, nowhere else — the same
rule docs/code-standards.md applies to selectors.py.

Everything below was read off Blinkit's own front-ends (2026-08-04), not guessed.
"""

# ── Marketing dashboard (brands.blinkit.com) ─────────────────────────────────
MARKETING_BASE = "https://brands.blinkit.com"

# The app's runtime Firebase config — a one-line file, far more stable to parse
# than the 9 MB JS bundle. `window.config.firebaseConfig` is read by
# getRuntimeFirebaseConfig() in the app itself.
MARKETING_CONFIG_JS = "/config.js"

# Blinkit issues the magic link itself; it is NOT firebase sendSignInLinkToEmail.
# The app's requestMagicLink() posts an empty body and carries the address in a
# header. Returns 200 {"status": true}; 401 when the address is not a real user.
MARKETING_REQUEST_MAGIC_LINK = "/adservice/v1/users/request-magic-link"

# Consuming the link IS stock Firebase, on Google's host — no Cloudflare in the
# way, which is why the whole login works over plain httpx.
FIREBASE_SIGNIN_EMAIL_LINK = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithEmailLink"
)
FIREBASE_REFRESH_TOKEN = "https://securetoken.googleapis.com/v1/token"

# Fallback only — the live value is fetched from config.js at login time so a
# rotation on Blinkit's side doesn't strand us.
MARKETING_FIREBASE_API_KEY_FALLBACK = "AIzaSyA258Mym_O68D-BQvoK8IUcTlyI0OrEFDQ"

# The app force-logs-out when lastLoginTime is older than this, INDEPENDENTLY of
# whether the Firebase refresh token is still good. `persistence` is set by the
# "Keep me signed in" checkbox. Our synthesized sessions always set persistence
# true and stamp lastLoginTime at restore, so we get the 7-day ceiling, not 1 day.
MARKETING_SESSION_DAYS_PERSISTENT = 7
MARKETING_SESSION_DAYS_DEFAULT = 1

# ── Seller dashboard (partnersbiz.com) ───────────────────────────────────────
# 2026-09-29: Blinkit is migrating seller accounts to seller.blinkit.com
# individually, not as a single platform-wide cutover — confirmed by Dobra's
# account (bhanu.na...@...) still logging in successfully here on 2026-09-29
# 06:10 while Sereko's account (kriti.agarwal@foresighttribe.com) gets
# {"action":"signup"} from send_otp and 500 "Verification failed" from
# verify_otp, because that specific account's identity has already been moved
# to seller.blinkit.com. See platform_auth/marketplaces/blinkit/seller_new.py
# for that domain's contract, wired 2026-09-30 as a SEPARATE registry slug
# (blinkit_seller_new) — NOT a swap of this constant, because
# seller.blinkit.com sits behind Cloudflare bot management that blocks plain
# httpx entirely, for both login AND data calls (proven 2026-09-30: even a
# live session's exact browser headers/cookies 403 when replayed over httpx —
# see seller_new.py). It needs a real browser for everything. Do not repoint
# SELLER_BASE here — every account still on partnersbiz.com (e.g. Dobra) would
# break, and this module's plain-httpx approach could never serve the new
# domain anyway.
SELLER_BASE = "https://partnersbiz.com"

SELLER_SEND_OTP = "/auth/api/v1/email/send_otp"
SELLER_VERIFY_OTP = "/auth/api/v1/email/verify_otp"
# Exchanges a refresh token for a fresh pair — a sliding window, so a live seller
# session never needs another OTP.
SELLER_ROTATE = "/auth/api/v1/tokens/rotate"
# The "account selection screen" from the old Playwright login, as an API call.
# Selection is pure client state (localStorage "myEntity"), so this is all it takes.
SELLER_USER_ENTITIES = "/v1/get-user-entities/"

# window.SUPPLY_KONG_CLIENT_ID — a public client id shipped to every browser.
SELLER_API_KEY = "fe25a1da-d76e-4da1-a7bf-175e8ecf130f"

# The auth service and the data service disagree about this header's spelling.
# Both are real: login calls send "partnersbiz-web", /v1/* calls "partnerbiz-web"
# (the typo is Blinkit's). Sending the wrong one is rejected.
SELLER_APP_CLIENT_AUTH = "partnersbiz-web"
SELLER_APP_CLIENT_DATA = "partnerbiz-web"
SELLER_SERVICE = "partnersbiz"

# Verified 2026-08-04: /v1/* data calls 403 with "ERROR_CODE:11 Unauthorised"
# unless these carry the selected entity. The token alone is not enough.
SELLER_ENTITY_ID_HEADER = "X-Entity-Id"
SELLER_ENTITY_TYPE_HEADER = "X-Entity-Type"

# ── Seller dashboard, new domain (seller.blinkit.com) ────────────────────────
# For accounts already migrated (e.g. Sereko's kriti.agarwal@foresighttribe.com).
# Confirmed via live DevTools capture 2026-09-29 (send_otp, verify_otp,
# resolve-account, and one data call — GET /seller-hub/api/app/feed). Not yet
# usable server-side: see the note on SELLER_BASE above.
SELLER_BASE_NEW = "https://seller.blinkit.com"
SELLER_RESOLVE_ACCOUNT = "/seller-hub/api/org/resolve-account"
SELLER_API_KEY_NEW = "0d0b54c3-8d3a-48fc-a433-1648b22e7e8d"
SELLER_APP_CLIENT_NEW = "seller-dashboard-web"
SELLER_SELLER_ID_HEADER = "x-gr-seller-id"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
