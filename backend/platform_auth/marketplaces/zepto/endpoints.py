"""Zepto auth endpoints and constants.

All URLs and static keys for the Zepto login live here, nowhere else — the same
rule docs/code-standards.md applies to selectors.py.

Everything below was read off Zepto's own front-end and verified against the live
BrikOven account (2026-08-20/22), not guessed.

Unlike Blinkit there is ONE console: `brands.zepto.co.in` covers ads *and* sales,
which is why this marketplace has a single authenticator rather than two.
"""

# The SPA is served from one host and talks to another. Both matter: the API
# checks Origin/Referer, so the console URL is not decoration.
CONSOLE = "https://brands.zepto.co.in"
API = "https://fcc.zepto.co.in"

# Two different application ids, both load-bearing, both constants of the app
# rather than per-brand values. Sending the wrong one fails the call.
#   APP_ID        — sign-in and MFA verification
#   PARENT_APP_ID — the get-user-by-token probe
APP_ID = "d0cd4873-7cb3-4c7c-9a25-3b109a0d2301"
PARENT_APP_ID = "1bddc95b-3201-4c15-b19a-ed03bd579f97"

# Phase 1: email + password. Returns 200 with every field null EXCEPT
# mfaEnabled/mfaId, and emails a 4-digit OTP. Zepto is the only marketplace here
# that needs a stored password — see Authenticator.needs_password.
SIGN_IN = "/api/v1/auth/sign-in"

# Phase 2: consume the OTP. Note the trailing slash — it is required.
VALIDATE_MFA_OTP = "/vendor/api/v1/auth/validate-mfa-otp/"

# Cheapest authenticated read; returns the caller's own identity. Used as `probe`.
GET_USER_BY_TOKEN = "/vendor/api/v1/auth/get-user-by-token"

# ── Header rules — each of these was learned the hard way ────────────────────
#
# 1. `authorization` carries the RAW JWT with NO "Bearer " prefix, despite the
#    login response advertising tokenType "Bearer". Prefixing it returns
#    'JWT Exception -> Unable to read JSON value' with a base64 decode error.
#
# 2. `/brand-analytics-web/*` needs `x-proxy-target: brand-analytics`. Without it
#    the gateway answers a bare text/plain 404 that reads like a wrong URL.
#
# 3. `/ads-bff/*` sits behind AWS WAF and needs BOTH a valid `x-aws-waf-token`
#    AND `waf-enabled: false`. Missing either, CloudFront answers 429 — which
#    looks exactly like rate limiting and is not. The WAF token is NOT a
#    credential (an anonymous browser mints one) and deliberately does not live
#    in this package; it belongs with whatever makes the data calls.
PROXY_TARGET_HEADER = "x-proxy-target"
PROXY_TARGET_BRAND_ANALYTICS = "brand-analytics"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# The OTP mail says "valid for 5 minutes" and it means it — much tighter than
# Blinkit's. mail_rules.py must not out-wait it.
OTP_VALID_SECONDS = 300
OTP_DIGITS = 4
