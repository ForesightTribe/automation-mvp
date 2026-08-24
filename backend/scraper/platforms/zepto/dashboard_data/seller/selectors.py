# Verified against the real Vendor Portal login page (brands.zepto.co.in) via
# live DevTools inspection (email/password/Log In/OTP/Confirm all confirmed).
LOGIN_URL = "https://brands.zepto.co.in/login"
# Bare origin (no path) — storage_state() origins are scheme+host only, so
# BASE_URL must match that exactly or the localStorage-merge check in
# auth.py's _capture_session silently never matches.
BASE_URL = "https://brands.zepto.co.in"

# ── Login ──────────────────────────────────────────────────────────────────────
LOGIN_EMAIL_INPUT = "input#email"
LOGIN_PASSWORD_INPUT = "input#password"
# No stable id/data-testid on this button — MUI's hash classes (e.g. css-zhtf44)
# can change on redeploys, so match on visible text instead, same as Blinkit's.
LOGIN_SUBMIT_PASSWORD_BUTTON = 'button:has-text("Log In")'

# Unlike Blinkit, Zepto's OTP is ONE text field (maxlength=4), not six
# per-digit boxes — filled directly, not typed digit-by-digit.
LOGIN_OTP_INPUT = "input#otp"
LOGIN_SUBMIT_OTP_BUTTON = 'button:has-text("Confirm")'

# Account selection screen (appears after OTP when multiple companies are
# linked). UNVERIFIED — copied from Blinkit's Ant Design selector as a
# placeholder; Brik Oven's login skipped this screen entirely, so it's never
# been checked against Zepto's actual UI (which is Material-UI everywhere
# else we've inspected, not Ant Design — this is very likely wrong).
LOGIN_ACCOUNT_CARD = 'span.ant-typography-ellipsis-single-line'
