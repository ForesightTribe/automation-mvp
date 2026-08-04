"""Show what is actually in the auth inbox, so mail rules can be pinned to reality.

The `from_contains` / `subject_contains` values in platform_auth/mail_rules.py
were inferred, not read off a real message. A wrong subject guess would make
auto-login fail at 3am with SecretNotFound. This prints the real headers so those
rules can be corrected once and marked `verified=True`.

    python -m scripts.inbox_scan [--limit 25] [--platform blinkit]

Read-only: opens the mailbox with readonly=True, prints headers only, and never
shows message bodies (they contain live magic links and OTPs). It reports whether
each message WOULD match a rule, and why not when it wouldn't.
"""
import argparse
import email
import imaplib
from email.header import decode_header, make_header

from app.core.config import settings
from platform_auth import mail_rules


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _sender_of(msg) -> str:
    return " ".join(_decode(msg.get(h)) for h in ("From", "Return-Path", "Sender")).lower()


def _recipients_of(msg) -> str:
    # To/Cc only — Delivered-To is the shared mailbox on every message.
    return " ".join(_decode(msg.get(h)) for h in ("To", "Cc")).lower()


def _verdict(msg, platform: str | None, login_email: str | None) -> str:
    """Which rules would accept this message, and where the near-misses are.

    Mirrors platform_auth/inbox/imap.py. If --email is given it also applies the
    recipient filter, which is what actually separates one tenant from another in
    this shared mailbox.
    """
    sender = _sender_of(msg)
    subject = _decode(msg.get("Subject")).lower()
    recipients = _recipients_of(msg)
    out = []
    for slug, rule in mail_rules.RULES.items():
        if platform and slug != platform:
            continue
        sender_ok = not rule.from_contains or any(s in sender for s in rule.from_contains)
        subject_ok = not rule.subject_contains or any(
            s in subject for s in rule.subject_contains
        )
        if not sender_ok:
            continue
        if rule.recipient_required and login_email:
            if login_email.lower() not in recipients:
                out.append(f"[{slug}: OTHER RECIPIENT]")
                continue
        if subject_ok:
            out.append(f"[MATCH {slug}]")
        elif rule.subject_required:
            out.append(f"[{slug}: rejected, subject]")
        else:
            out.append(f"[{slug}: subject miss, ADVISORY -> would use]")
    return " ".join(out) or "-"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--platform", default=None, help="Only evaluate this rule")
    parser.add_argument(
        "--email",
        default=None,
        help="Tenant login address — applies the recipient filter, as a real login would",
    )
    args = parser.parse_args()

    if not (settings.AUTH_INBOX_USER and settings.AUTH_INBOX_APP_PASSWORD):
        raise SystemExit(
            "AUTH_INBOX_USER / AUTH_INBOX_APP_PASSWORD are not set in .env — "
            "nothing to scan."
        )

    print(f"Mailbox: {settings.AUTH_INBOX_USER} / {settings.AUTH_INBOX_FOLDER}\n")
    with imaplib.IMAP4_SSL(settings.AUTH_INBOX_HOST) as conn:
        conn.login(settings.AUTH_INBOX_USER, settings.AUTH_INBOX_APP_PASSWORD)
        conn.select(settings.AUTH_INBOX_FOLDER, readonly=True)
        status, data = conn.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            raise SystemExit("Mailbox is empty.")

        for msg_id in reversed(data[0].split()[-args.limit:]):
            # Headers only — bodies hold live secrets and must not be printed.
            status, raw = conn.fetch(msg_id, "(BODY.PEEK[HEADER])")
            if status != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            msg = email.message_from_bytes(raw[0][1])
            print(f"date    : {_decode(msg.get('Date'))}")
            print(f"from    : {_decode(msg.get('From'))}")
            print(f"to      : {_decode(msg.get('To'))}")
            delivered = _decode(msg.get("Delivered-To"))
            if delivered:
                print(f"deliv-to: {delivered}")
            print(f"subject : {_decode(msg.get('Subject'))}")
            print(f"verdict : {_verdict(msg, args.platform, args.email)}")
            print("-" * 78)

    print(
        "\nPin `from_contains` / `subject_contains` in "
        "platform_auth/mail_rules.py to what you see above, then set verified=True."
    )


if __name__ == "__main__":
    main()
