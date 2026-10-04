"""ZC-D1 — the marketplace is part of every campaign-manager address, with no default.

Mounts ONLY the campaign-manager router on a bare FastAPI app, with the client and DB-session
dependencies replaced and the service functions stubbed — no server, no database, no queue.
What it pins is the HTTP contract the frontend relies on:

  * `/campaign-manager/<marketplace>/…` reaches the service WITH that marketplace;
  * an unknown marketplace is a 404 naming the valid ones;
  * an old un-prefixed address is a 400 that says what the new one is;
  * the one marketplace-free route left (`GET /jobs/{id}`, a status read) still works.

    python -m campaign_manager.tests.test_cm_api_marketplace
"""
import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import CurrentUser, get_client, get_session, require_admin
from app.routes import campaign_manager as routes
from app.services import campaign_manager_service as svc

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")
BASE = f"/clients/{TENANT}/campaign-manager"


def _client(stubs: dict) -> tuple[TestClient, list]:
    """A TestClient over the router, with `svc.<name>` replaced by recorders from `stubs`."""
    app = FastAPI()
    app.include_router(routes.router, prefix="/clients/{client_id}/campaign-manager")
    app.dependency_overrides[get_client] = lambda: SimpleNamespace(id=TENANT)
    app.dependency_overrides[get_session] = lambda: None
    # Writes are admin-gated; these tests are about marketplace routing, not auth.
    app.dependency_overrides[require_admin] = lambda: CurrentUser(
        user_id=str(uuid.uuid4()), account_id=str(uuid.uuid4()), role="admin"
    )
    calls: list = []
    originals = {}
    for name, result in stubs.items():
        originals[name] = getattr(svc, name)

        def _make(n, res):
            async def _stub(*args, **kwargs):
                calls.append((n, args, kwargs))
                return res(*args, **kwargs) if callable(res) else res
            return _stub
        setattr(svc, name, _make(name, result))
    _client.restore = lambda: [setattr(svc, n, f) for n, f in originals.items()]
    return TestClient(app), calls


def _with(stubs):
    def deco(fn):
        def run():
            client, calls = _client(stubs)
            try:
                fn(client, calls)
            finally:
                _client.restore()
        run.__name__ = fn.__name__
        return run
    return deco


# ── the marketplace reaches the service ─────────────────────────────────────

@_with({"list_bid_rules": []})
def test_the_marketplace_in_the_address_reaches_the_service(client, calls):
    for mp in ("blinkit", "zepto"):
        r = client.get(f"{BASE}/{mp}/bid-rules")
        assert r.status_code == 200, r.text
    assert [c[1][1] for c in calls] == ["blinkit", "zepto"]


@_with({"list_bid_rules": []})
def test_the_marketplace_is_case_insensitive(client, calls):
    assert client.get(f"{BASE}/Zepto/bid-rules").status_code == 200
    assert calls[0][1][1] == "zepto"


@_with({"set_budget_now": uuid.UUID(int=1)})
def test_an_action_carries_the_marketplace(client, calls):
    r = client.post(f"{BASE}/zepto/set-budget", json={"campaign_id": 2427461, "budget": 600})
    assert r.status_code == 200, r.text
    name, args, _ = calls[0]
    assert args[2] == "zepto" and args[3] == 2427461


@_with({"get_live": True})
def test_the_live_switch_is_readable_per_marketplace(client, calls):
    r = client.get(f"{BASE}/zepto/live")
    assert r.status_code == 200 and r.json() == {"marketplace": "zepto", "live": True}


# ── what is refused ─────────────────────────────────────────────────────────

@_with({"list_bid_rules": []})
def test_an_unknown_marketplace_is_404_and_names_the_valid_ones(client, calls):
    r = client.get(f"{BASE}/swiggy/bid-rules")
    assert r.status_code == 404
    assert "blinkit" in r.json()["detail"] and "zepto" in r.json()["detail"]
    assert calls == [], "the service must never be reached"


@_with({"list_bid_rules": [], "set_budget_now": uuid.UUID(int=1)})
def test_an_old_address_without_a_marketplace_is_400_and_says_the_new_one(client, calls):
    for method, path in (("get", "/bid-rules"), ("get", "/budget-schedules"),
                         ("post", "/set-budget"), ("post", "/campaigns/refresh"),
                         ("get", "/history")):
        r = getattr(client, method)(f"{BASE}{path}")
        assert r.status_code == 400, (path, r.status_code, r.text)
        assert "/campaign-manager/<marketplace>/" in r.json()["detail"], path
    assert calls == []


@_with({"update_bid_rule": None})
def test_a_rule_of_the_other_marketplace_is_not_found_here(client, calls):
    """The service returns None when the id belongs to another marketplace; the route
    says so in words, not just 404."""
    r = client.patch(f"{BASE}/zepto/bid-rules/abc", json={"target_position": 2})
    assert r.status_code == 404 and "Zepto automations" in r.json()["detail"]


@_with({"list_bid_rules": []})
def test_a_wrong_method_on_a_real_path_is_not_blamed_on_the_marketplace(client, calls):
    r = client.delete(f"{BASE}/blinkit/bid-rules")
    assert r.status_code in (404, 405)
    assert "<marketplace>" not in r.text


# ── the one marketplace-free route ──────────────────────────────────────────

@_with({"get_job": lambda *a, **k: {"id": str(uuid.UUID(int=7)), "job_type": "cm.set_budget",
                                   "status": "done", "created_at": "2026-09-24T12:00:00"}})
def test_the_plain_job_poll_still_works_and_says_it_is_marketplace_free(client, calls):
    r = client.get(f"{BASE}/jobs/{uuid.UUID(int=7)}")
    assert r.status_code == 200, r.text
    assert calls[0][2] == {"marketplace": None}


@_with({"get_job": None})
def test_a_job_polled_under_a_marketplace_is_checked_against_it(client, calls):
    client.get(f"{BASE}/zepto/jobs/{uuid.UUID(int=7)}")
    assert calls[0][2] == {"marketplace": "zepto"}


# ── E3: the keyword picker's address ────────────────────────────────────────

@_with({"list_catalog_keywords": []})
def test_the_keyword_list_is_per_marketplace(client, calls):
    r = client.get(f"{BASE}/zepto/keywords")
    assert r.status_code == 200, r.text
    assert calls[0][1][1] == "zepto"
    assert client.get(f"{BASE}/nowhere/keywords").status_code == 404


# ── the page-load overview (2026-09-25) ─────────────────────────────────────

@_with({"overview": {"budget_schedules": [], "bid_rules": [], "history": [],
                     "history_total": 0, "wallet": None, "live": False}})
def test_the_overview_is_per_marketplace(client, calls):
    r = client.get(f"{BASE}/zepto/overview")
    assert r.status_code == 200, r.text
    assert calls[0][1][1] == "zepto"
    assert r.json()["live"] is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} campaign-manager API marketplace tests passed.")
