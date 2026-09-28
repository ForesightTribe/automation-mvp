"""Instamart Brand Portal auth endpoints and constants.

All URLs and static keys for the Instamart login live here, nowhere else — the
same rule the Blinkit and Zepto modules follow.

Everything below was read off the portal's own front-end and verified against the
live Brik Oven account on 2026-09-21, not guessed.

THREE hosts, and the split matters:

    partner.instamart.in                 the SPA (login page, dashboards)
    ozone-idp-brands-im-kba.swiggy.com   identity — send OTP, verify OTP, refresh
    brand-portal-service-http.swiggy.com DATA — campaigns, metrics, sales, …

Auth talks only to the identity host, over plain HTTP, no cookies, no browser:
Blinkit-seller-shaped. The data host is a different story (see SIGNATURE below)
and belongs to the private scraper, not to this package.

ONE portal covers sales, ads, requisition orders and catalog, so — like Zepto,
unlike Blinkit — the marketplace has a single authenticator.
"""

PORTAL = "https://partner.instamart.in"
IDP = "https://ozone-idp-brands-im-kba.swiggy.com"
DATA = "https://brand-portal-service-http.swiggy.com"

# The portal's fixed OAuth-style client id — a constant of the app shipped to
# every browser, not a per-brand value. Sent on all three identity calls.
CLIENT_ID = "f4e72b9a-5fde-4d1a-9e74-0237bcf4d67f"

# Phase 1: email in, OTP mail out. Returns {user_id, session_info}; both go back
# verbatim in phase 2. `user_id` here is a 64-hex hash — NOT the numeric id the
# JWT later carries as `sub`, which is what refresh wants.
SEND_VERIFICATION_CODE = "/v1/accounts/sendVerificationCode"

# Phase 2: {otp, user_id, session_info, client_id} -> {access_token, refresh_token}.
# The OTP mail: From no-reply@swiggy.in, "Your Login OTP for Swiggy Instamart Ads
# Portal", 6 digits, single use, 10 minutes — see platform_auth/mail_rules.py.
SIGN_IN_WITH_OTP = "/v1/accounts/signInWithOTP"

# {user_id: <JWT sub>, refresh_token, client_id} -> {access_token, refresh_token,
# expires_at}. Observed: the refresh token does NOT rotate (same value back), the
# access token is reissued for another 5 h, `expires_at` is epoch seconds. The
# page calls this right after login and again on its own — no new OTP.
TOKEN_REFRESH = "/v1/token/refresh"

OTP_DIGITS = 6

# Access token: RS256 JWT, `exp - iat` = 5 h on every one captured. Claims worth
# keeping: sub (numeric user id), email, session_id, siat (session issued-at —
# unchanged across refreshes, so it dates the OTP that started the session).
ACCESS_TOKEN_HOURS = 5

# ── Data-call headers ────────────────────────────────────────────────────────
# What every brand-portal-service call carried (captured on /api/v1/campaigns
# and /api/v1/advertiser/metrics). The bearer token is NOT enough on its own:
#
#   authorization        Bearer <access_token>
#   x-client-account-id  <advertiser account id>   -> the "entity" of this portal
#   x-client-id          IM_ADS_EXTERNAL_DASHBOARD
#   app_version          1.4.136
#   x-client-request-id  <uuid, per request>
#   x-timestamp          <ms epoch, per request>
#   x-signature          <64 hex, per request>     -> SIGNATURE, see below
#
# The account id is the same value that appears as `accid=` inside the ad
# tracking context of the brand's own ads on the public search — the private
# and public sides join on it. It is not in the JWT and is not returned by any
# identity call, so it is stored per tenant in platform_credentials.extra
# (`account_id`), the way Blinkit's entity is resolved once and kept.
DATA_CLIENT_ID = "IM_ADS_EXTERNAL_DASHBOARD"
APP_VERSION = "1.4.136"
ACCOUNT_ID_KEY = "account_id"          # key in Credentials.extra / raw

# SIGNATURE. Tested 2026-09-21 by replaying /advertiser/metrics with a live
# token: without x-signature, with a garbage one, and with fresh ids — all 403
# "PermissionDenied: Request Forbidden: Please reload the browser". The
# signature is computed in the portal's JavaScript per request (two calls with
# the same x-timestamp had different signatures, so it covers the request id
# and/or body). Consequence for THIS package: probe() must not use a data
# call; it goes through TOKEN_REFRESH, which needs no signature. How the
# private scraper obtains signatures is its own problem (replicate the signing,
# or issue calls from inside a logged-in page).
