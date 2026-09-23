"""ZC-C19 — every marketplace adapter offers what the engines call.

Adapters are MODULES, so nothing makes them implement anything: a function one marketplace
lacks fails only when an engine reaches it, in production, on that marketplace. That has
happened — Zepto had no `read_bid_floors`, and every Zepto bid tick crashed.

A RATCHET, not a hand-kept list: the required surface is read from the engines' own source
(every `adapter.<name>(` in `campaign_manager/*.py`), so a new call is covered the moment it
is written. A name the engines only reach through `getattr(adapter, "<name>"` /
`hasattr(adapter, "<name>"` is OPTIONAL — they already cope with its absence.

    python -m campaign_manager.tests.test_adapter_contract
"""
import inspect
import re
from pathlib import Path

from campaign_manager.marketplaces import base, get_adapter, supported

_ENGINES = Path(__file__).resolve().parents[1]
_CALL = re.compile(r"\badapter\.([a-z_][a-z0-9_]*)\(")
_GUARDED = re.compile(r"(?:getattr|hasattr)\(\s*adapter\s*,\s*[\"']([a-z_][a-z0-9_]*)[\"']")


def _code_lines(path: Path):
    """Source lines with comments and docstring-ish prose dropped — a function NAMED in a
    comment ("it used to call `adapter._api_match(...)`") is not a call."""
    in_doc = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or line.startswith("#") or line.startswith('"""'):
            continue
        yield raw.split("  #")[0]


def _engine_surface() -> tuple[set[str], set[str]]:
    called, guarded = set(), set()
    for path in _ENGINES.glob("*.py"):
        text = "\n".join(_code_lines(path))
        called |= set(_CALL.findall(text))
        guarded |= set(_GUARDED.findall(path.read_text(encoding="utf-8")))
    return called - guarded, guarded


def test_the_scan_finds_the_engines_real_calls():
    """Guards the guard: a regex that silently matched nothing would pass every adapter."""
    required, _ = _engine_surface()
    for name in ("setup", "read_campaign", "apply_budget", "apply_bid", "apply_status",
                 "read_bid_floors", "fetch_positions", "locate_position"):
        assert name in required, f"the scan no longer sees `adapter.{name}(` — fix the scan"


def _missing(adapter, required) -> list[str]:
    return sorted(n for n in required if not hasattr(adapter, n))


def _lacking_args(adapter) -> list[str]:
    contract = {name: fn for name, fn in vars(base.CampaignAdapter).items()
                if callable(fn) and not name.startswith("_")}
    out = []
    for name, spec in contract.items():
        impl = getattr(adapter, name, None)
        if impl is None:
            continue                          # presence is checked separately
        want, _ = _params(spec)
        have, open_kw = _params(impl)
        if not open_kw and want - have:
            out.append(f"{name} lacks {sorted(want - have)}")
    return out


def test_every_adapter_has_every_function_the_engines_call():
    required, _ = _engine_surface()
    missing = {slug: _missing(get_adapter(slug), required) for slug in supported()}
    assert not any(missing.values()), (
        f"adapter functions the engines call but a marketplace lacks: "
        f"{ {k: v for k, v in missing.items() if v} } — each would crash the first run "
        f"that reaches it on that marketplace")


def test_sync_and_async_agree_across_adapters():
    """`await adapter.x()` on a plain function raises; calling an async one without await
    silently does nothing. Both adapters must agree on which each function is."""
    required, _ = _engine_surface()
    adapters = {slug: get_adapter(slug) for slug in supported()}
    for name in sorted(required):
        kinds = {slug: inspect.iscoroutinefunction(getattr(a, name))
                 for slug, a in adapters.items() if hasattr(a, name)}
        assert len(set(kinds.values())) <= 1, f"{name}: async on some, sync on others {kinds}"


def _params(fn) -> tuple[set[str], bool]:
    sig = inspect.signature(fn)
    names = {p.name for p in sig.parameters.values()
             if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)}
    open_kw = any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values())
    return names - {"self"}, open_kw


def test_every_adapter_accepts_every_argument_the_contract_declares():
    """The engines pass arguments BY NAME (`merchant_id=`, `budget=`, `match_type=`). An
    adapter missing one raises TypeError on the call — the crash this file exists for."""
    problems = {slug: _lacking_args(get_adapter(slug)) for slug in supported()}
    assert not any(problems.values()), problems


def test_guarded_names_are_optional_not_required():
    """A name the engines reach only through getattr/hasattr copes with absence, so it must
    not be demanded — otherwise every optional hook (Zepto's hold reasons, its eligibility
    rule) would force a stub onto Blinkit."""
    required, guarded = _engine_surface()
    assert {"hold_reason", "automation_refusal"} <= guarded
    assert not ({"hold_reason", "automation_refusal"} & required)


# ── the checks catch a broken adapter (a test that has only passed proves little) ──

def test_a_missing_function_is_caught():
    from types import SimpleNamespace

    required, _ = _engine_surface()
    zepto = get_adapter("zepto")
    broken = SimpleNamespace(**{n: getattr(zepto, n) for n in required
                                if n != "read_bid_floors"})
    assert _missing(broken, required) == ["read_bid_floors"], (
        "the exact 2026-09 crash: Zepto without read_bid_floors")


def test_a_missing_keyword_argument_is_caught():
    from types import SimpleNamespace

    async def fetch_positions(session, keyword, lat, lon):      # no merchant_id
        return []

    broken = SimpleNamespace(fetch_positions=fetch_positions)
    assert any("merchant_id" in p for p in _lacking_args(broken))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} adapter contract tests passed.")
