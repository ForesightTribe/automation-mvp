"""Which email to look for, per platform — the inbox reader's entire knowledge.

Every marketplace's magic links and OTPs are auto-forwarded into ONE mailbox, so
"find the login mail" is a real matching problem. All of that matching lives
here, in data, so that adding a marketplace or fixing a changed subject line is a
one-line edit and never a code change.

## How a message is judged

Filters run strongest-first. The order matters more than the individual rules:

1. **Recipient** — the challenge's own address must appear in To/Cc. **This is the
   filter that keeps tenants apart**, and it is not optional. Verified against the
   real mailbox on 2026-08-04: `tech@` already receives "Sign in to Blinkit Brand
   Central" addressed to *three different people* (bhanu@foresighttribe.com,
   oxbowbrands@joharsgroup.com, srimanta.chatterjee@joharsgroup.com) — same sender,
   same subject, different accounts. Without this check, a login for one tenant can
   consume another's magic link: logging into the wrong account, or silently burning
   their single-use code. Match **To/Cc, never Delivered-To** — forwarding sets
   Delivered-To to the shared mailbox on *every* message, so it discriminates nothing.
2. **Arrival time** — only mail newer than `challenge.requested_at` can answer the
   request we just made. Without it a stale OTP from an earlier attempt reads as
   valid and the login fails a minute later for reasons that look unrelated.
3. **Sender** — `from_contains`, matched against From + Return-Path. Use the full
   address where it is known: a bare domain is too loose when one company runs
   several products. `blinkit_seller` originally listed `"blinkit"` here, which made
   it match the *marketing* dashboard's mail from `brands@blinkit.com` — and since
   subjects were advisory, a seller login could have pulled six digits out of a
   marketing email.
4. **Subject** — `subject_contains`, **required by default**. Both senders also send
   routine mail from the same address ("Dashboard Reports", "Ad Campaign Alert",
   "Search Reports"), and a login must never mistake a report for its secret.
   Advisory mode was a hedge while the real subjects were unknown; now that they are
   verified, requiring them is strictly safer. Leave it False only for a platform
   whose subjects are still guesses.
5. **Shape** — `body_pattern` must actually extract something. A message that
   passes every filter but contains no code is not the message.

## Timing

`initial_delay_seconds` exists because mail is not instant: the platform queues
it, SendGrid relays it, and forwarding adds another hop. Polling immediately just
burns IMAP round-trips on an empty mailbox. Wait, then poll.

Blinkit rules were **verified against real messages on 2026-08-04** via
`scripts/inbox_scan.py`. Zepto and Instamart are still guesses — and are wired
`False` in the registry, so nothing can reach them.
"""
from dataclasses import dataclass, field

from platform_auth.types import SecretKind


@dataclass(frozen=True)
class MailRule:
    """Everything needed to find and read one platform's login mail."""

    platform: str
    secret_kind: SecretKind

    # ── Matching ──────────────────────────────────────────────────────────────
    # Substrings matched case-insensitively against From / Return-Path.
    # Any one hit is enough. Match the full sender address where you know it —
    # a bare domain is too loose when one company runs several products.
    from_contains: tuple[str, ...] = ()
    # Substrings matched against the decoded Subject. Any one hit is enough.
    subject_contains: tuple[str, ...] = ()
    # Promote the subject from tiebreaker to hard requirement. Default True:
    # these senders also send routine mail (reports, campaign alerts), and a
    # login flow must never mistake a report for its secret.
    subject_required: bool = True
    # Require the challenge's own address in To/Cc. THE strongest filter in a
    # shared inbox — see the class docstring.
    recipient_required: bool = True
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
        # Real message 2026-08-04:
        #   From:    Blinkit Brand Central <brands@blinkit.com>
        #   Subject: Sign in to Blinkit Brand Central
        # The same address also sends "Dashboard Reports" and "Ad Campaign Alert"
        # several times a day, which is why the subject is REQUIRED here.
        from_contains=("brands@blinkit.com",),
        subject_contains=("sign in to blinkit brand central",),
        subject_required=True,
        body_pattern=r"https?://[^\s\"'<>\]]+",
        # The link that lands is a ct.sendgrid.net click-tracking wrapper.
        link_hints=("sendgrid", "oobcode", "auth"),
        # Magic links are single-use: if anything opens it before we do, the
        # exchange fails. It is why we resolve redirects manually rather than
        # loading the /auth/action page (whose JS is what consumes the code).
        initial_delay_seconds=8.0,
        timeout_seconds=120.0,
        notes=(
            "brands.blinkit.com. Firebase action link, SendGrid-wrapped, single-use. "
            "Note no-reply@blinkit.com is a DIFFERENT sender that mails reports only."
        ),
        verified=True,
    ),
    "blinkit_seller": MailRule(
        platform="blinkit_seller",
        secret_kind=SecretKind.OTP,
        # Real message 2026-08-04:
        #   From:    Partners Biz <noreply@partnersbiz.com>
        #   Subject: Your OTP for PartnersBiz login
        # ⚠️ Do NOT add "blinkit" here. It was here originally and made this rule
        # match brands@blinkit.com — the marketing dashboard's mail — from which a
        # six-digit pattern would happily extract a wrong "OTP".
        from_contains=("noreply@partnersbiz.com",),
        subject_contains=("your otp for partnersbiz login",),
        subject_required=True,
        # A six-digit run not embedded in a longer number.
        body_pattern=r"(?<!\d)(\d{6})(?!\d)",
        # OTP mail has been slower than the magic link in practice, and a stale OTP
        # is the prime suspect for the one historical login failure — so wait a
        # little longer before the first look rather than racing it.
        initial_delay_seconds=12.0,
        timeout_seconds=150.0,
        notes="partnersbiz.com. 6-digit OTP, expires quickly — read it fast.",
        verified=True,
    ),
    # ── Planned ───────────────────────────────────────────────────────────────
    # Fill in from a real message when the platform is wired up; until then the
    # authenticator is wired=False so nothing can reach these.
    # Guesses. subject_required=False until a real message is seen — an unverified
    # subject must not be able to veto. Flip it to True the moment it IS verified;
    # a shared inbox makes a loose rule dangerous, not merely useless.
    "zepto": MailRule(
        platform="zepto",
        secret_kind=SecretKind.OTP,
        from_contains=("zepto", "zeptonow"),
        subject_contains=("otp", "verification", "code"),
        subject_required=False,
        body_pattern=r"(?<!\d)(\d{4,6})(?!\d)",
        notes="Email + password login, with an OTP second factor. See docs/zepto.md.",
        verified=False,
    ),
    "instamart": MailRule(
        platform="instamart",
        secret_kind=SecretKind.OTP,
        from_contains=("swiggy", "instamart"),
        subject_contains=("otp", "verification", "code"),
        subject_required=False,
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
