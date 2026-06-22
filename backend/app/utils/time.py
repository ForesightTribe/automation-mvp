from datetime import datetime, timedelta, timezone

# India Standard Time. India observes no DST, so a fixed +05:30 offset is always
# correct and avoids depending on the system / tzdata timezone database.
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Current wall-clock time in IST as a naive datetime (no tzinfo).

    All timestamps in this app are stored as naive IST wall-clock values in
    TIMESTAMP WITHOUT TIME ZONE columns. Use this everywhere instead of
    datetime.utcnow() / datetime.now(timezone.utc).
    """
    return datetime.now(IST).replace(tzinfo=None)
