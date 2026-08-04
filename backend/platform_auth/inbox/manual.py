"""The human fallback — what `cli auth` did before, behind the SecretSource interface.

Still needed for: the first login of a new tenant (nothing is stored yet), any
platform whose mail isn't forwarded, and as the escape hatch when the inbox
reader can't find the message.

Runs input() in an executor so it doesn't block the event loop.
"""
import asyncio

from platform_auth.types import LoginChallenge, SecretKind

_PROMPTS = {
    SecretKind.MAGIC_LINK: "Paste the magic link from your email: ",
    SecretKind.OTP: "Enter the 6-digit OTP from your email: ",
}


async def get_secret(challenge: LoginChallenge) -> str:
    prompt = _PROMPTS.get(challenge.secret_kind, "Enter the login secret: ")
    loop = asyncio.get_event_loop()
    value = await loop.run_in_executor(None, lambda: input(prompt))
    return value.strip()
