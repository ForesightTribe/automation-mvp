"""Where a login secret comes from.

Two implementations, one signature: `manual` (a human pastes into the terminal)
and `imap` (read the forwarding mailbox). Keeping this an interface is what lets
first-ever logins stay manual — proving the account, surviving anything
unexpected — while every subsequent one runs unattended.

The signature takes the challenge, not just an email, because finding the right
message in a SHARED inbox needs three things: who it's from, what it looks like,
and — critically — that it arrived *after* we asked. Auto-forwarding puts every
marketplace's mail in one mailbox, so without the timestamp cutoff a stale OTP
from an hour ago looks like a valid answer.
"""
from typing import Awaitable, Callable

from platform_auth.types import LoginChallenge

# get_secret(challenge) -> the magic link or OTP
SecretSource = Callable[[LoginChallenge], Awaitable[str]]
