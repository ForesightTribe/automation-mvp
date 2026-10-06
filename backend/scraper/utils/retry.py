import asyncio
import functools
from typing import Any, Awaitable, Callable

from app.utils.logger import logger


async def retry_call(
    fn: Callable[[], Awaitable[Any]],
    *,
    waits: tuple[float, ...],
    retry_if: Callable[[Exception], bool],
    label: str,
) -> Any:
    """Call `fn()`; when it raises an exception `retry_if` accepts, wait `waits[i]`
    and call it again — one retry per wait. Anything else, or the last failure,
    propagates unchanged.

    For endpoints whose failures are measured, not guessed: the caller states exactly
    WHICH failures are worth repeating (a 5xx usually is; a 4xx or an auth failure
    never is) and the waits that cleared them. `retry` below retries every exception
    on an exponential ladder, which would replay those that cannot fix themselves.
    """
    for attempt, wait in enumerate((*waits, None)):
        try:
            return await fn()
        except Exception as e:
            if wait is None or not retry_if(e):
                raise
            logger.debug(f"{label} failed ({e}) — attempt {attempt + 1}, retrying in {wait}s")
            await asyncio.sleep(wait)


def retry(max_attempts: int = 3, delay: float = 2.0, backoff: float = 2.0):
    """Exponential backoff retry decorator for async functions."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    logger.debug(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {current_delay}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
        return wrapper
    return decorator
