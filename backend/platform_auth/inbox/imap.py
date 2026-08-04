"""Read the login secret out of the forwarding mailbox over IMAP.

All matching knowledge — senders, subjects, patterns, timing — lives in
`platform_auth/mail_rules.py`, not here. This module only executes it.

stdlib `imaplib` is blocking with no async port, so every call runs in an
executor. That is also why this polls rather than holding an IMAP IDLE
connection: a handful of polls over a ~2 minute window is simpler and cheaper,
and logins are rare.
"""
import asyncio
import email
import imaplib
import re
from datetime import timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime

from app.core.config import settings
from app.utils.logger import logger
from app.utils.time import IST, now_ist
from platform_auth import mail_rules
from platform_auth.errors import SecretNotFound
from platform_auth.mail_rules import MailRule
from platform_auth.types import LoginChallenge, SecretKind

# Mail can be stamped a few seconds before our clock says we asked; without a
# grace window we would discard the very message we triggered.
_CLOCK_GRACE = timedelta(seconds=30)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _body_text(msg: Message) -> str:
    """Flatten a message to searchable text (plain text and HTML alike)."""
    parts: list[str] = []
    targets = msg.walk() if msg.is_multipart() else [msg]
    for part in targets:
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(part.get_content_charset() or "utf-8", "ignore"))
        except Exception:
            continue
    return "\n".join(parts)


def _sender_of(msg: Message) -> str:
    return " ".join(
        _decode(msg.get(h)) for h in ("From", "Return-Path", "Sender")
    ).lower()


def _recipients_of(msg: Message) -> str:
    """To/Cc only — deliberately NOT Delivered-To.

    Forwarding stamps Delivered-To with the shared mailbox on every message, so
    including it would make this check pass for everything. To/Cc preserve the
    address the platform actually sent to, which is the only thing distinguishing
    our tenant's magic link from another company's.
    """
    return " ".join(_decode(msg.get(h)) for h in ("To", "Cc")).lower()


def _is_recent(msg: Message, challenge: LoginChallenge) -> bool:
    raw = msg.get("Date")
    if not raw:
        return False
    try:
        sent = parsedate_to_datetime(raw)
    except Exception:
        return False
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=IST)
    sent_ist = sent.astimezone(IST).replace(tzinfo=None)
    return sent_ist >= challenge.requested_at - _CLOCK_GRACE


def _extract(msg: Message, rule: MailRule) -> str | None:
    text = _body_text(msg)

    if rule.secret_kind is SecretKind.OTP:
        m = re.search(rule.body_pattern, text)
        return (m.group(1) if m.groups() else m.group(0)) if m else None

    candidates = re.findall(rule.body_pattern, text)
    if not candidates:
        return None
    for url in candidates:
        if any(hint in url.lower() for hint in rule.link_hints):
            return url.rstrip(").,")
    return candidates[0].rstrip(").,")


def _addressed_to_us(msg: Message, challenge: LoginChallenge) -> bool:
    """Is this OUR tenant's mail, or someone else's?

    The single most important check in a shared inbox. This mailbox demonstrably
    receives the same sender/subject addressed to several different accounts, so
    without it a login can consume another tenant's single-use secret.
    """
    return challenge.email.lower() in _recipients_of(msg)


def _score(msg: Message, rule: MailRule) -> tuple[bool, bool]:
    """(sender matched, subject matched)."""
    sender = _sender_of(msg)
    subject = _decode(msg.get("Subject")).lower()
    sender_ok = not rule.from_contains or any(s in sender for s in rule.from_contains)
    subject_ok = not rule.subject_contains or any(s in subject for s in rule.subject_contains)
    return sender_ok, subject_ok


def _search_once(challenge: LoginChallenge, rule: MailRule) -> str | None:
    """One blocking IMAP round-trip. Runs in an executor.

    Collects every message that passes the hard filters, then prefers one whose
    subject also matches — so a stale subject rule costs us nothing when only one
    candidate exists, but still disambiguates when several arrive together.
    """
    with imaplib.IMAP4_SSL(settings.AUTH_INBOX_HOST) as conn:
        conn.login(settings.AUTH_INBOX_USER, settings.AUTH_INBOX_APP_PASSWORD)
        conn.select(settings.AUTH_INBOX_FOLDER, readonly=True)

        # IMAP SINCE is day-granular, so it only narrows the set; the real cutoff
        # is _is_recent(), on the message's own Date header.
        since = (challenge.requested_at - timedelta(days=1)).strftime("%d-%b-%Y")
        status, data = conn.search(None, f'(SINCE "{since}")')
        if status != "OK" or not data or not data[0]:
            return None

        fallback: str | None = None
        for msg_id in reversed(data[0].split()[-rule.scan_limit:]):  # newest first
            status, raw = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            msg = email.message_from_bytes(raw[0][1])

            if not _is_recent(msg, challenge):
                continue
            # Hard filter, ahead of sender/subject: another tenant's secret is not
            # ours to read, and consuming it burns their single-use code.
            if rule.recipient_required and not _addressed_to_us(msg, challenge):
                continue
            sender_ok, subject_ok = _score(msg, rule)
            if not sender_ok:
                continue
            if rule.subject_required and not subject_ok:
                continue

            secret = _extract(msg, rule)
            if not secret:
                continue

            subject = _decode(msg.get("Subject"))
            if subject_ok:
                logger.info(f"Login mail matched for {rule.platform}: {subject[:70]!r}")
                return secret
            if fallback is None:
                logger.warning(
                    f"{rule.platform}: sender matched but subject did not "
                    f"({subject[:70]!r}) — using it anyway. Consider updating "
                    f"subject_contains in platform_auth/mail_rules.py."
                )
                fallback = secret

        return fallback


async def get_secret(challenge: LoginChallenge, timeout: float | None = None) -> str:
    """Wait for, find, and return the secret we just triggered."""
    if not (settings.AUTH_INBOX_USER and settings.AUTH_INBOX_APP_PASSWORD):
        raise SecretNotFound(challenge.platform, 0)

    rule = mail_rules.for_platform(challenge.platform)
    budget = timeout if timeout is not None else rule.timeout_seconds

    # Mail is not instant — the platform queues it, a relay forwards it, and
    # forwarding adds another hop. Polling immediately just burns round-trips.
    if rule.initial_delay_seconds:
        logger.info(
            f"Waiting {rule.initial_delay_seconds:.0f}s for the {rule.platform} "
            f"{rule.secret_kind.value} to arrive…"
        )
        await asyncio.sleep(rule.initial_delay_seconds)

    loop = asyncio.get_event_loop()
    deadline = now_ist() + timedelta(seconds=budget)
    attempt = 0

    while now_ist() < deadline:
        attempt += 1
        try:
            secret = await loop.run_in_executor(None, _search_once, challenge, rule)
        except Exception as e:
            # A transient IMAP hiccup should not abort an otherwise fine login.
            logger.warning(f"IMAP read failed (attempt {attempt}): {e}")
            secret = None
        if secret:
            return secret
        await asyncio.sleep(rule.poll_seconds)

    raise SecretNotFound(challenge.platform, budget)
