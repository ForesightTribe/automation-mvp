"""
Bid Optimizer — real-time rank-chasing keyword bid controller for Blinkit.

For each active rule:
  1. Fetch campaign detail -> get current CPM bid
  2. Scrape blinkit.com (consumer side) for the keyword -> find campaign
     product's sponsored position in real-time (replaces lagged 24h report)
  3. Compare with target_position
  4. Adjust CPM bid by dynamic step (distance-based)

Step formula:
  distance >= 4  ->  Rs 100
  distance >= 3  ->  Rs 50
  distance >= 1  ->  Rs 25
  distance <  1  ->  Rs 12.5

Position source:
  Primary:  blinkit.com consumer scrape (real-time, location-specific)
  Fallback: campaign report API most_viewed_position (24h average)

If the campaign product is not found as a sponsored ad in search results,
treat as position 50 so the optimizer keeps raising the bid.
"""
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Isolated executor so consumer scraping runs in its own thread + event loop,
# completely separate from the marketing session Playwright instance.
_scrape_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live_scrape")


def _run_scrape_sync(keyword: str, lat: float, lon: float) -> list[dict]:
    """Run blinkit.com consumer scrape in a fresh event loop (Windows-safe)."""
    from ad_campaigns.live_position import get_live_positions
    # Windows requires ProactorEventLoop for Playwright subprocess support
    if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        print(f"[live_scrape] starting scrape keyword={keyword} lat={lat} lon={lon}", flush=True)
        results = loop.run_until_complete(get_live_positions(keyword, lat=lat, lon=lon))
        print(f"[live_scrape] done — {len(results)} results", flush=True)
        for r in results[:25]:
            print(f"  #{r['position']} [{'Ad' if r.get('is_ad') else 'organic'}] {r['name']}", flush=True)
        return results
    except Exception as e:
        import traceback
        print(f"[live_scrape] EXCEPTION: {e}", flush=True)
        traceback.print_exc()
        raise  # let optimizer fall back to report API
    finally:
        try:
            loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_DIR = Path(__file__).parent
_RULES_FILE = _DIR / "bid_optimizer_rules.json"
_LOG_FILE   = _DIR / "bid_optimizer_log.json"
_COOLDOWN_HOURS = 0  # real-time data — no lag, scheduler interval is the pace


def _dynamic_step(distance: float) -> float:
    if distance >= 4: return 100
    if distance >= 3: return 50
    if distance >= 1: return 25
    return 12.5


def _load_rules() -> list[dict]:
    if not _RULES_FILE.exists():
        return []
    return json.loads(_RULES_FILE.read_text(encoding="utf-8"))


def _save_rules(rules: list[dict]) -> None:
    _RULES_FILE.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_log(entry: dict) -> None:
    entries: list[dict] = []
    if _LOG_FILE.exists():
        entries = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
    entries.append(entry)
    _LOG_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _is_active(rule: dict, now: datetime) -> bool:
    today        = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    start_date   = rule.get("start_date")
    stop_date    = rule.get("stop_date")
    if start_date and today < start_date:
        return False
    if stop_date and today > stop_date:
        return False
    start_time = rule.get("start_time")
    stop_time  = rule.get("stop_time")
    if start_time and stop_time:
        if not (start_time <= current_time <= stop_time):
            return False
    return True


def _find_product_position(
    results: list[dict],
    product_names: list[str],
    brand_name: str | None = None,
    product_pids: list[str] | None = None,
) -> tuple[float | None, bool, bool]:
    """
    Returns (sponsored_position, is_sponsored, product_found).

    Matching priority:
      1. PID match  — definitive
      2. Name keywords — meaningful words from product names
      3. brand_name fallback — when product names are PID-only stubs
    """
    if not results:
        return None, False, False

    pid_set = {str(p).strip() for p in (product_pids or []) if p}

    stop_words = {"soda", "water", "drink", "pack", "combo", "with", "from", "and",
                  "the", "zero", "sugar", "lime", "mint", "ginger", "cola",
                  "product", "item", "type", "name"}
    keywords: set[str] = set()
    for name in product_names:
        if name.startswith("Product (ID:"):
            continue
        for word in name.lower().split():
            word_clean = word.strip("(),:.-")
            if len(word_clean) > 3 and word_clean not in stop_words and word_clean.isalpha():
                keywords.add(word_clean)

    if not keywords and brand_name:
        keywords.add(brand_name.lower().strip())

    match_desc = f"pids={pid_set or 'none'} keywords={keywords or 'none'} brand={brand_name}"
    print(f"[bid_opt] searching for sponsored Ad — {match_desc} in {len(results)} results", flush=True)

    organic_match = None
    for item in results:
        item_pid = str(item.get("pid") or "").strip()
        item_lower = item["name"].lower()

        pid_match = bool(item_pid and pid_set and item_pid in pid_set)
        name_match = bool(keywords and any(kw in item_lower for kw in keywords))

        if pid_match or name_match:
            match_type = "PID" if pid_match else "name"
            is_sponsored = bool(item.get("is_ad"))
            if is_sponsored:
                print(
                    f"[bid_opt] FOUND sponsored [{match_type}] pos={item['position']} "
                    f"name={item['name']} pid={item_pid}",
                    flush=True,
                )
                return float(item["position"]), True, True
            elif organic_match is None:
                organic_match = (item, match_type, item_pid)

    if organic_match is not None:
        item, match_type, item_pid = organic_match
        print(
            f"[bid_opt] found organic [{match_type}] pos={item['position']} "
            f"name={item['name']} pid={item_pid} — no sponsored Ad found, skip",
            flush=True,
        )
        return None, False, True

    print(f"[bid_opt] product NOT found in {len(results)} results ({match_desc}) — skip", flush=True)
    return None, False, False


async def run(client) -> list[dict]:
    rules    = _load_rules()
    now_ist  = datetime.now(_IST)
    now_str  = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    log_entries: list[dict] = []

    # Group rules by campaign
    by_campaign: dict[int, list[dict]] = {}
    for rule in rules:
        if not rule.get("active", True):
            continue
        if not _is_active(rule, now_ist):
            continue
        by_campaign.setdefault(rule["campaign_id"], []).append(rule)

    for campaign_id, camp_rules in by_campaign.items():
        campaign_name = camp_rules[0].get("campaign_name", str(campaign_id))

        # ── current CPM bids from campaign detail ────────────────────────────
        try:
            detail, _ = await client.get_campaign_detail(campaign_id)
            existing_kws = (
                (detail.get("campaign_targeting") or {})
                .get("keyword_targeting", {})
                .get("keywords", [])
            ) or detail.get("keywords", [])
            kw_cpm_map = {
                k["keyword"]: k["bids"][0].get("cpm", 0)
                for k in existing_kws
                if k.get("bids")
            }
        except Exception as e:
            entry = {
                "timestamp": now_str, "campaign_id": campaign_id,
                "campaign_name": campaign_name, "keyword": None,
                "action": "ERROR", "detail": f"Campaign detail fetch failed: {e}",
                "success": False,
            }
            log_entries.append(entry); _append_log(entry)
            continue

        # ── campaign products (used to match in live search results) ─────────
        try:
            camp_products = await client.get_campaign_products(campaign_id)
            product_names = [p.get("name", "") for p in camp_products if p.get("name")]
            product_pids  = [str(p["pid"]) for p in camp_products if p.get("pid")]
            print(f"[bid_opt] campaign={campaign_id} products: pids={product_pids} names={product_names[:3]}", flush=True)
        except Exception as e:
            log.warning("[bid_opt] product fetch failed campaign=%d: %s", campaign_id, e)
            product_names = []
            product_pids  = []

        # ── report API as fallback position source ────────────────────────────
        try:
            report_rows = await client.get_campaign_report(campaign_id, days=1)
            kw_pos_map = {
                r.get("keyword", ""): r.get("most_viewed_position")
                for r in report_rows if r.get("keyword")
            }
            kw_imp_map = {
                r.get("keyword", ""): r.get("impressions", 0)
                for r in report_rows if r.get("keyword")
            }
        except Exception as e:
            log.warning("[bid_opt] report fetch failed campaign=%d: %s", campaign_id, e)
            kw_pos_map = {}
            kw_imp_map = {}

        keyword_updates: list[dict] = []
        position_updates: dict[str, float] = {}

        for rule in camp_rules:
            keyword    = rule["keyword"]
            target     = rule["target_position"]
            min_bid    = rule.get("min_bid") or kw_cpm_map.get(keyword) or 50
            max_bid    = rule["max_bid"]
            match_type = rule.get("match_type", "EXACT")
            rule_id    = rule.get("id", "")
            current_cpm = rule.get("last_cpm") or kw_cpm_map.get(keyword) or min_bid

            # ── cooldown check ────────────────────────────────────────────────
            if _COOLDOWN_HOURS > 0:
                last_updated = rule.get("last_bid_updated_at")
                if last_updated:
                    elapsed_h = (now_ist - datetime.fromisoformat(last_updated)).total_seconds() / 3600
                    if elapsed_h < _COOLDOWN_HOURS:
                        entry = {
                            "timestamp": now_str, "campaign_id": campaign_id,
                            "campaign_name": campaign_name, "keyword": keyword,
                            "action": f"COOLDOWN: last changed {elapsed_h:.1f}h ago — waiting {_COOLDOWN_HOURS}h",
                            "old_cpm": current_cpm, "new_cpm": current_cpm, "success": True,
                        }
                        log_entries.append(entry); _append_log(entry)
                        continue

            # ── REAL-TIME position via consumer scraping (primary) ────────────
            pos_source = "report"
            impressions = kw_imp_map.get(keyword, 0)

            try:
                lat = float(rule.get("lat") or 12.9767)
                lon = float(rule.get("lon") or 77.5713)
                log.info(
                    "[bid_opt] scraping blinkit.com keyword=%s lat=%s lon=%s",
                    keyword, lat, lon,
                )
                loop = asyncio.get_event_loop()
                live_results = await loop.run_in_executor(
                    _scrape_executor,
                    _run_scrape_sync,
                    keyword, lat, lon,
                )
                log.info(
                    "[bid_opt] scrape returned %d results for keyword=%s\n  %s",
                    len(live_results),
                    keyword,
                    "\n  ".join(
                        f"#{r['position']} [{'Ad' if r.get('is_ad') else 'organic'}] {r['name']}"
                        for r in live_results[:25]
                    ),
                )
                live_pos, is_sponsored, product_found = _find_product_position(
                    live_results, product_names,
                    brand_name=rule.get("brand_name"),
                    product_pids=product_pids,
                )

                if live_pos is None:
                    if not product_found:
                        if not product_pids:
                            reason = "PIDs missing from Blinkit — product not found in live search"
                        else:
                            reason = "product not found in live search results"
                    else:
                        reason = "organic only (not a campaign Ad)"
                    entry = {
                        "timestamp": now_str, "campaign_id": campaign_id,
                        "campaign_name": campaign_name, "keyword": keyword,
                        "action": f"SKIP: {reason}",
                        "old_cpm": current_cpm, "new_cpm": current_cpm,
                        "position": None, "target_position": target,
                        "impressions": impressions, "success": True,
                    }
                    log_entries.append(entry); _append_log(entry)
                    continue

                current_position = live_pos
                position_updates[rule_id] = current_position
                pos_source = f"LIVE-Ad(lat={lat},lon={lon})"
                log.info(
                    "[bid_opt] LIVE sponsored position campaign=%d keyword=%s pos=%.1f",
                    campaign_id, keyword, current_position,
                )

            except Exception as e:
                import traceback
                print(f"[bid_opt] LIVE SCRAPE FAILED for keyword={keyword}: {e}", flush=True)
                traceback.print_exc()
                log.warning("[bid_opt] live scrape failed, falling back to report: %s", e)
                report_pos = kw_pos_map.get(keyword)
                if report_pos is not None:
                    current_position = float(report_pos)
                    position_updates[rule_id] = current_position
                    pos_source = "report(fallback)"
                else:
                    current_position = 50.0
                    pos_source = "report(no data)"

            distance = abs(current_position - target)
            step     = _dynamic_step(distance)

            if current_position > target:
                last_pos = rule.get("last_position")
                if last_pos is not None and current_position >= last_pos:
                    # Position hasn't improved — check if we've waited long enough
                    # for Blinkit to reflect the previous bid change.
                    last_updated = rule.get("last_bid_updated_at")
                    minutes_held = (
                        (now_ist - datetime.fromisoformat(last_updated)).total_seconds() / 60
                        if last_updated else 999
                    )
                    if minutes_held < 10:
                        # Still within reflection window — hold and wait.
                        entry = {
                            "timestamp": now_str, "campaign_id": campaign_id,
                            "campaign_name": campaign_name, "keyword": keyword,
                            "action": (
                                f"HOLD: pos {current_position} (was {last_pos}) — no improvement yet"
                                f" | {pos_source} | holding Rs{current_cpm}"
                                f" | {minutes_held:.0f}min since last bid change"
                            ),
                            "old_cpm": current_cpm, "new_cpm": current_cpm,
                            "position": current_position, "target_position": target,
                            "impressions": impressions, "success": True,
                        }
                        log_entries.append(entry); _append_log(entry)
                        position_updates[rule_id] = current_position
                        continue
                    # 30+ min held — Blinkit has had time to reflect.
                    # Current bid isn't enough; force an increase.
                new_cpm = min(int(current_cpm + step), max_bid)
                action  = (
                    f"↑ pos {current_position} > target {target} "
                    f"| {pos_source} | impressions={impressions} "
                    f"| step Rs{step} | Rs{current_cpm}->Rs{new_cpm}"
                )
            elif current_position < target:
                new_cpm = max(int(current_cpm - step), min_bid)
                action  = (
                    f"↓ pos {current_position} < target {target} "
                    f"| {pos_source} | step Rs{step} | Rs{current_cpm}->Rs{new_cpm}"
                )
            else:
                entry = {
                    "timestamp": now_str, "campaign_id": campaign_id,
                    "campaign_name": campaign_name, "keyword": keyword,
                    "action": f"TARGET ACHIEVED: position {current_position} == target {target} | {pos_source}",
                    "old_cpm": current_cpm, "new_cpm": current_cpm,
                    "position": current_position, "target_position": target,
                    "impressions": impressions, "success": True,
                }
                log_entries.append(entry); _append_log(entry)
                continue

            entry = {
                "timestamp": now_str, "campaign_id": campaign_id,
                "campaign_name": campaign_name, "keyword": keyword,
                "action": action, "old_cpm": current_cpm, "new_cpm": new_cpm,
                "position": None if current_position == 50 else current_position,
                "target_position": target, "impressions": impressions, "success": True,
            }

            if new_cpm != current_cpm:
                # blinkit API only accepts "EXACT" or "SMART" — map legacy "BROAD" value
                api_match_type = "SMART" if match_type == "BROAD" else match_type
                keyword_updates.append({
                    "keyword": keyword, "match_type": api_match_type, "cpm": new_cpm,
                    "_rule_id": rule_id, "_entry": entry,
                })
            else:
                _append_log(entry); log_entries.append(entry)

        # ── save last_position for rules with no bid change ───────────────────
        no_update_positions = {
            rid: pos for rid, pos in position_updates.items()
            if rid not in {u["_rule_id"] for u in keyword_updates}
        }
        if no_update_positions:
            all_rules = _load_rules()
            for r in all_rules:
                if r["campaign_id"] == campaign_id and r.get("id") in no_update_positions:
                    r["last_position"] = no_update_positions[r.get("id")]
            _save_rules(all_rules)

        # ── apply bid updates ─────────────────────────────────────────────────
        if keyword_updates:
            try:
                resp = await client.update_keyword_bids(
                    campaign_id,
                    [{"keyword": u["keyword"], "match_type": u["match_type"], "cpm": u["cpm"]}
                     for u in keyword_updates],
                )
                success = bool(resp.get("status") or resp.get("success"))
                for u in keyword_updates:
                    e = u["_entry"]; e["success"] = success
                    if not success:
                        e["detail"] = str(resp)
                    _append_log(e); log_entries.append(e)

                if success:
                    updated_map = {u["keyword"]: u["cpm"] for u in keyword_updates}
                    all_rules = _load_rules()
                    for r in all_rules:
                        if r["campaign_id"] == campaign_id:
                            if r["keyword"] in updated_map:
                                r["last_cpm"]            = updated_map[r["keyword"]]
                                r["last_bid_updated_at"] = now_ist.isoformat()
                            rid = r.get("id", "")
                            if rid in position_updates:
                                r["last_position"] = position_updates[rid]
                    _save_rules(all_rules)

            except Exception as e:
                for u in keyword_updates:
                    entry = u["_entry"]
                    entry["success"] = False; entry["detail"] = str(e)
                    _append_log(entry); log_entries.append(entry)

    return log_entries


async def run_with_state(storage_state: dict) -> list[dict]:
    from ad_campaigns.client import setup_with_state
    pw, browser, client = await setup_with_state(storage_state)
    try:
        return await run(client)
    finally:
        await browser.close()
        await pw.stop()
