"""Which email to look for, per platform — the inbox reader's entire knowledge.

Every marketplace's magic links and OTPs are auto-forwarded into ONE mailbox, so
"find the login mail" is a real matching problem. All of that matching lives
here, in data, so that adding a marketplace or fixing a changed subject line is a
one-line edit and never a code change.

## How a message is judged

Filters run strongest-first. The order matters more than the individual rules:

1. **Arrival time** — only mail newer than `challenge.requested_at` can answer the
   request we just made. This is the load-bearing filter. Without it a stale OTP
   from an earlier attempt reads as valid and the login fails a minute later for
   reasons that look unrelated.
2. **Sender** — `from_contains`, matched against From + Return-Path +
   Delivered-To. Forwarding rewrites headers, so match on fragments (a domain)
   rather than a full address.
3. **Subject** — `subject_contains`. **Advisory by default.** A subject rule that
   is merely out of date should not make auto-login fail; it breaks the tie when
   several candidate messages arrive together. Set `subject_required=True` only
   when a platform sends several kinds of mail from one address and the subject
   is genuinely the only discriminator.
4. **Shape** — `body_pattern` must actually extract something. A message that
   passes every filter but contains no code is not the message.

## Timing

`initial_delay_seconds` exists because mail is not instant: the platform queues
it, SendGrid relays it, and forwarding adds another hop. Polling immediately just
burns IMAP round-trips on an empty mailbox. Wait, then poll.

⚠️ **The subject lines below are UNVERIFIED for both platforms** (marked per
rule). They were inferred, not read off a real message. Pin them with
`scripts/inbox_scan.py` before trusting auto-login unattended.
"""
from dataclasses import dataclass, field

from platform_auth.types import SecretKind


@dataclass(frozen=True)
class MailRule:
    """Everything needed to find and read one platform's login mail."""

    platform: str
    secret_kind: SecretKind

    # ── Matching ──────────────────────────────────────────────────────────────
    # Substrings matched case-insensitively against From / Return-Path /
    # Delivered-To. Any one hit is enough.
    from_contains: tuple[str, ...] = ()
    # Substrings matched against the decoded Subject. Any one hit is enough.
    subject_contains: tuple[str, ...] = ()
    # Promote the subject from tiebreaker to hard requirement.
    subject_required: bool = False
    # Regex that pulls the secret out of the body. Group 1 if present, else whole match.
    body_pattern: str = r"https?://[^\s\"'<>]+"
    # Prefer URLs containing these when several match (magic links only).
    link_hints: tuple[str, ...] = ()

    # ── Timing ────────────────────────────────────────────────────────────────
    # Wait this long before the first poll — the mail has to arrive first.
    initial_delay_seconds: float = 8.0
    poll_seconds: float = 3.0
    # Total budget before giving up, measured from the initial delay.
    timeout_seconds: float = 120.0
    # How many of the newest messages to examine per poll.
    scan_limit: int = 15

    notes: str = ""
    verified: bool = False  # have we seen a REAL message of this kind?


RULES: dict[str, MailRule] = {
    "blinkit": MailRule(
        platform="blinkit",
        secret_kind=SecretKind.MAGIC_LINK,
        # Blinkit sends the magic link through SendGrid — the link that lands is a
        # ct.sendgrid.net click-tracking wrapper (confirmed 2026-08-04).
        from_contains=("blinkit", "sendgrid", "grofers"),
        subject_contains=("sign in", "signin", "magic link", "login", "log in"),
        subject_required=False,   # UNVERIFIED — must not be allowed to veto
        body_pattern=r"https?://[^\s\"'<>\]]+",
        link_hints=("oobcode", "sendgrid", "blinkit", "auth"),
        # Magic links are single-use: if anything opens it before we do, the
        # exchange fails. Nothing to do about it here, but it is why we resolve
        # redirects manually rather than loading the page.
        initial_delay_seconds=8.0,
        timeout_seconds=120.0,
        notes="brands.blinkit.com. Firebase action link, SendGrid-wrapped, single-use.",
        verified=False,
    ),
    "blinkit_seller": MailRule(
        platform="blinkit_seller",
        secret_kind=SecretKind.OTP,
        from_contains=("partnersbiz", "blinkit", "grofers"),
        subject_contains=("otp", "verification", "verify", "code"),
        subject_required=False,   # UNVERIFIED
        # A six-digit run not embedded in a longer number.
        body_pattern=r"(?<!\d)(\d{6})(?!\d)",
        # OTP mail has been slower than the magic link in practice, and a stale
        # OTP is the prime suspect for the one historical login failure — so wait
        # a little longer before the first look rather than racing it.
        initial_delay_seconds=12.0,
        timeout_seconds=150.0,
        notes="partnersbiz.com. 6-digit OTP, expires quickly — read it fast.",
        verified=False,
    ),
    # ── Planned ───────────────────────────────────────────────────────────────
    # Fill in from a real message when the platform is wired up; until then the
    # authenticator is wired=False so nothing can reach these.
    "zepto": MailRule(
        platform="zepto",
        secret_kind=SecretKind.OTP,
        from_contains=("zepto", "zeptonow"),
        subject_contains=("otp", "verification", "code"),
        body_pattern=r"(?<!\d)(\d{4,6})(?!\d)",
        notes="Email + password login, with an OTP second factor. See docs/zepto.md.",
        verified=False,
    ),
    "instamart": MailRule(
        platform="instamart",
        secret_kind=SecretKind.OTP,
        from_contains=("swiggy", "instamart"),
        subject_contains=("otp", "verification", "code"),
        body_pattern=r"(?<!\d)(\d{4,6})(?!\d)",
        notes="Not investigated yet.",
        verified=False,
    ),
}


def for_platform(platform: str) -> MailRule:
    rule = RULES.get(platform)
    if rule is None:
        raise KeyError(
            f"No mail rule for {platform!r}. Add one to platform_auth/mail_rules.py "
            f"— known: {', '.join(sorted(RULES))}"
        )
    return rule


def unverified() -> list[str]:
    """Platforms whose rules have never been checked against a real message."""
    return sorted(p for p, r in RULES.items() if not r.verified)
