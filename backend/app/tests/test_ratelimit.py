"""Login rate limiter — the counting rules, with no database or HTTP involved."""
from app.utils import ratelimit as rl

WINDOW = 900.0


def setup_function():
    rl._fails.clear()


def test_allows_up_to_the_limit_then_blocks():
    for _ in range(5):
        assert rl.check("email", "a@b.c", 5, WINDOW) is None
        rl.record_failure("email", "a@b.c", WINDOW)
    assert rl.check("email", "a@b.c", 5, WINDOW) is not None


def test_block_reports_a_wait_within_the_window():
    for _ in range(5):
        rl.record_failure("email", "a@b.c", WINDOW)
    wait = rl.check("email", "a@b.c", 5, WINDOW)
    assert 0 < wait <= WINDOW


def test_checking_a_blocked_identity_does_not_extend_the_lockout():
    for _ in range(5):
        rl.record_failure("email", "a@b.c", WINDOW)
    first = rl.check("email", "a@b.c", 5, WINDOW)
    for _ in range(20):
        rl.check("email", "a@b.c", 5, WINDOW)
    assert rl.check("email", "a@b.c", 5, WINDOW) <= first


def test_success_clears_the_identity():
    for _ in range(5):
        rl.record_failure("email", "a@b.c", WINDOW)
    rl.clear("email", "a@b.c")
    assert rl.check("email", "a@b.c", 5, WINDOW) is None


def test_identities_and_buckets_are_independent():
    for _ in range(5):
        rl.record_failure("email", "a@b.c", WINDOW)
    assert rl.check("email", "other@b.c", 5, WINDOW) is None
    assert rl.check("ip", "a@b.c", 5, WINDOW) is None


def test_expired_failures_fall_out_of_the_window():
    for _ in range(5):
        rl.record_failure("email", "a@b.c", 0.0)
    assert rl.check("email", "a@b.c", 5, 0.0) is None


def test_empty_identity_is_never_limited():
    # A request with no resolvable IP must not share one bucket with every
    # other such request, which would lock them all out together.
    for _ in range(50):
        rl.record_failure("ip", "", WINDOW)
    assert rl.check("ip", "", 5, WINDOW) is None


def test_client_ip_prefers_cloudflare_then_forwarded_then_peer():
    class R:
        def __init__(self, headers, peer="10.0.0.1"):
            self.headers = headers
            self.client = type("C", (), {"host": peer})()

    assert rl.client_ip(R({"cf-connecting-ip": "1.1.1.1",
                           "x-forwarded-for": "2.2.2.2"})) == "1.1.1.1"
    assert rl.client_ip(R({"x-forwarded-for": "2.2.2.2, 3.3.3.3"})) == "2.2.2.2"
    assert rl.client_ip(R({})) == "10.0.0.1"
