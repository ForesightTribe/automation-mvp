/**
 * Insights: React Query hooks.
 *
 * Re-exported from the Ads feature for the same reason as api.js: identical contract, so
 * sharing the module also shares the query cache. That is deliberate while both pages
 * exist, because the same numbers rendered twice must not disagree.
 */
export * from "../ads/hooks";

import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import { getCampaigns, getPerformance, getBudgetSplit } from "../ads/api";
import { useAdsSummary } from "../ads/hooks";
import { getBreakdowns, getCampaignsDaily, getKeywordInsights } from "./api";

/** The key a campaign is known by everywhere on this page. Campaign ids are per-marketplace
 * namespaces, so an id alone could name two campaigns. */
export const campaignKey = (c) => `${c.platform}:${c.campaign_id}`;

/**
 * The keyword table's data: `{ periods, items }` — one row per campaign × keyword × match
 * type across marketplaces (see getKeywordInsights). Grouping by keyword needs the whole
 * set: grouping a page of twenty would split a keyword's campaigns across pages.
 */
export const useKeywordInsights = ({ enabled = true } = {}) => {
	const { activeClientId } = useClient();
	const { selected, ready } = useMarketplaces();
	const { range } = useDateRange();
	return useQuery({
		queryKey: ["insights-keywords", activeClientId, selected, range],
		queryFn: () =>
			getKeywordInsights(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId) && ready && enabled,
		staleTime: 5 * 60 * 1000,
	});
};

/** One breakdown dimension's rows (see getBreakdowns). Only fetched when `enabled` — the
 * card asks only when a marketplace in scope reports breakdowns. */
export const useBreakdowns = ({ dimension, adType = "", enabled = true }) => {
	const { activeClientId } = useClient();
	const { selected, ready } = useMarketplaces();
	const { range } = useDateRange();
	return useQuery({
		queryKey: [
			"insights-breakdowns",
			activeClientId,
			selected,
			range,
			dimension,
			adType,
		],
		queryFn: () =>
			getBreakdowns(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				dimension,
				adType,
			}),
		enabled: Boolean(activeClientId) && ready && enabled,
		placeholderData: keepPreviousData,
	});
};

/**
 * The window immediately before the selected one, of the same length.
 *
 * "Is this good?" is unanswerable from one number, so every comparison here is against the
 * period that just ended rather than an arbitrary baseline: a 30-day view compares with the
 * 30 days before it, and changing the picker moves both windows together.
 */
export const usePreviousRange = () => {
	const { range } = useDateRange();
	// ⚠️ N1 (2026-10-08): the KPI summary says which days actually have ad data — a window
	// ending today ends on a day not scraped yet — and the previous window it compared with.
	// Every comparison on the page uses that same pair, so a chart never sets 6 days of data
	// against 7. Until the summary lands, the picker's own previous window.
	const { data: summary } = useAdsSummary();
	const p = summary?.period;
	if (p?.prev_start && p?.prev_end) {
		const days =
			Math.round(
				(new Date(p.prev_end) - new Date(p.prev_start)) / 86400000,
			) + 1;
		return { from: p.prev_start, to: p.prev_end, days };
	}
	const from = new Date(range.from);
	const to = new Date(range.to);
	const days = Math.max(1, Math.round((to - from) / 86400000) + 1);
	const prevTo = new Date(from);
	prevTo.setDate(prevTo.getDate() - 1);
	const prevFrom = new Date(prevTo);
	prevFrom.setDate(prevFrom.getDate() - (days - 1));
	const iso = (d) => d.toISOString().slice(0, 10);
	return { from: iso(prevFrom), to: iso(prevTo), days };
};

/**
 * The window's days that have ad data: from the picker's start to the newest day with data
 * (the KPI summary's `period.end`), and how many days that is. Budget utilisation divides by
 * these days, not by days not scraped yet (N1). Until the summary lands, the picker's window.
 */
export const useDataWindow = () => {
	const { range } = useDateRange();
	const { data: summary } = useAdsSummary();
	const end = summary?.period?.end ?? range.to;
	const days = Math.max(
		1,
		Math.round((new Date(end) - new Date(range.from)) / 86400000) + 1,
	);
	return { from: range.from, to: end, days, partial: end < range.to };
};

/** Daily rows for the previous window. Only fetched once a comparison is opened. */
export const usePreviousPerformance = (enabled = false) => {
	const { activeClientId } = useClient();
	const { selected, ready } = useMarketplaces();
	const prev = usePreviousRange();
	return useQuery({
		queryKey: [
			"insights-prev-performance",
			activeClientId,
			prev.from,
			prev.to,
			selected,
		],
		queryFn: () =>
			getPerformance(activeClientId, {
				start: prev.from,
				end: prev.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId && enabled) && ready,
		staleTime: 5 * 60 * 1000,
	});
};

/** Spend split for the previous window, for the same reason. */
export const usePreviousBudgetSplit = (enabled = false) => {
	const { activeClientId } = useClient();
	const { selected, ready } = useMarketplaces();
	const prev = usePreviousRange();
	return useQuery({
		queryKey: [
			"insights-prev-split",
			activeClientId,
			prev.from,
			prev.to,
			selected,
		],
		queryFn: () =>
			getBudgetSplit(activeClientId, {
				start: prev.from,
				end: prev.to,
				marketplaces: selected,
			}),
		enabled: Boolean(activeClientId && enabled) && ready,
		staleTime: 5 * 60 * 1000,
	});
};

const isoDay = (d) => d.toISOString().slice(0, 10);

/**
 * Budget utilisation for each of the last N days, one day at a time.
 *
 * There is no per-campaign daily endpoint, so this asks `/ads/campaigns` for a window of a
 * single day, N times over. Each call answers "what did every campaign spend on this date,
 * and what is its daily budget", which is exactly the numerator and denominator.
 *
 * ⚠️ Two things that would make the number wrong if skipped:
 *
 *  - A single-day window still returns EVERY campaign on the account, including the ~200
 *    that did not run. Counting their budgets in the denominator drags utilisation down by
 *    roughly twenty points (28.7% against 49.9% on 4 Sep). Only campaigns that actually
 *    spent that day are counted, on both sides of the division.
 *  - `daily_budget` is a CURRENT snapshot, not history. Nothing records what a campaign's
 *    budget was on a past date, so each day is measured against today's budget. For a
 *    campaign under budget automation that is precisely what changes, so treat older days
 *    as an approximation rather than a ledger.
 *
 * Verified against SQL over `blinkit_ad_campaign_daily`: 43.8 / 49.9 / 58.2 for 3, 4 and
 * 5 Sep from both paths.
 */
export const MAX_BU_DAYS = 31;

/** Every date in the selected range, oldest first, capped so a 90-day view cannot fan out. */
const rangeDates = (from, to) => {
	const out = [];
	const end = new Date(to);
	const cur = new Date(from);
	while (cur <= end && out.length < MAX_BU_DAYS) {
		out.push(isoDay(cur));
		cur.setDate(cur.getDate() + 1);
	}
	// A long window keeps its most RECENT days, which is the end anybody is looking at.
	if (out.length === MAX_BU_DAYS) {
		const back = [];
		const c2 = new Date(to);
		while (back.length < MAX_BU_DAYS) {
			back.unshift(isoDay(c2));
			c2.setDate(c2.getDate() - 1);
		}
		return back;
	}
	return out;
};

/** The last N days ending at `to`, oldest first. */
const lastNDates = (to, n) => {
	const out = [];
	const cur = new Date(to);
	for (let i = 0; i < Math.min(n, MAX_BU_DAYS); i += 1) {
		out.unshift(isoDay(cur));
		cur.setDate(cur.getDate() - 1);
	}
	return out;
};

/**
 * Budget utilisation per day, and per campaign per day, over the window.
 *
 * ⚠️ ONE request (`/ads/campaigns/daily`), not one per day. This used to ask `/ads/campaigns`
 * once per date — up to 31 requests, walked four at a time so they would not exhaust the
 * API's connection pool — and each still held a pooled connection. The server now returns
 * every campaign's spend per day in one go, row for row what the per-day calls returned
 * (verified 2026-09-25: 2,926 rows, 0 differences), and the derivation below is unchanged.
 */
export const useDailyBudgetUtilisation = ({
	enabled = true,
	days = null,
} = {}) => {
	const { activeClientId } = useClient();
	const { selected, ready } = useMarketplaces();
	const { range } = useDateRange();

	// `days` asks for the last N days ending at the window's end, which is what a "7 day
	// trend" means. Without it the whole selected window is used, capped.
	//
	// ⚠️ Three days of slack when a fixed span is asked for. The newest calendar days usually
	// have no scrape yet, and dropping them (below) would otherwise leave a "7 day" strip
	// with 6 dots. Asking for 10 and keeping the last 7 that survive gives seven real ones.
	const dates = days
		? lastNDates(range.to, days + 3)
		: rangeDates(range.from, range.to);

	const query = useQuery({
		queryKey: [
			"ads-bu-days",
			activeClientId,
			selected,
			dates[0],
			dates[dates.length - 1],
		],
		queryFn: () =>
			getCampaignsDaily(activeClientId, {
				start: dates[0],
				end: dates[dates.length - 1],
				marketplaces: selected,
			}),
		enabled:
			enabled && Boolean(activeClientId) && dates.length > 0 && ready,
		// A past day never changes once its scrape has landed, so this is cheap to hold.
		staleTime: 15 * 60 * 1000,
	});

	const dateKey = dates.join(",");
	const allSettled = query.isSuccess || query.isError;
	const derived = useMemo(() => {
		// The rows for each date, in the shape the per-day calls used to return.
		const byDate = new Map(dates.map((d) => [d, []]));
		for (const r of query.data ?? []) byDate.get(r.date)?.push(r);
		const itemsOn = (date) => byDate.get(date) ?? [];

		const all = dates.map((date) => {
			const items = itemsOn(date);
			const live = items.filter(
				(c) => (c.budget_consumed ?? 0) > 0 && c.daily_budget,
			);
			const spend = live.reduce((s, c) => s + c.budget_consumed, 0);
			const allowed = live.reduce((s, c) => s + c.daily_budget, 0);
			return {
				date,
				spend,
				allowed,
				campaigns: live.length,
				bu: allowed ? (spend / allowed) * 100 : null,
			};
		});

		// Trailing days with nothing in them are days the scrape has not reached, not days of
		// zero spend, so they are dropped rather than drawn as a floor. Only once the answer
		// is in — before that every day looks empty.
		let end = all.length;
		if (allSettled) {
			while (end > 0 && all[end - 1].campaigns === 0) end -= 1;
		}
		const start = days ? Math.max(0, end - days) : 0;
		const rows = all.slice(start, end);
		const kept = dates.slice(start, end);

		/**
		 * The same figures at campaign × day grain, which is what a per-campaign view needs.
		 *
		 * A campaign appears if it spent on ANY day in the window; days it did not run stay
		 * null rather than zero, because "did not run" and "ran and spent nothing" are
		 * different facts and only one of them is a utilisation failure.
		 */
		const byCampaign = new Map();
		kept.forEach((date, di) => {
			for (const c of itemsOn(date)) {
				if (!((c.budget_consumed ?? 0) > 0) || !c.daily_budget)
					continue;
				const key = campaignKey(c);
				if (!byCampaign.has(key)) {
					byCampaign.set(key, {
						key,
						campaign_id: c.campaign_id,
						platform: c.platform,
						name: c.name,
						type: c.type,
						days: kept.map((d) => ({
							date: d,
							spend: null,
							allowed: null,
							bu: null,
							sales: null,
							roas: null,
						})),
						total: 0,
						totalSales: 0,
					});
				}
				const row = byCampaign.get(key);
				row.days[di] = {
					date,
					spend: c.budget_consumed,
					allowed: c.daily_budget,
					bu: (c.budget_consumed / c.daily_budget) * 100,
					// Carried through from the same response: utilisation without return is half
					// the story, since underspending at 5x costs far more than at 1x.
					sales: c.ad_sales,
					roas: c.budget_consumed
						? c.ad_sales / c.budget_consumed
						: null,
				};
				row.total += c.budget_consumed;
				row.totalSales += c.ad_sales ?? 0;
			}
		});

		return {
			rows,
			dates: kept,
			campaigns: [...byCampaign.values()].sort(
				(a, b) => b.total - a.total,
			),
		};
		// `dataUpdatedAt` and `dateKey` ARE the dependencies: `dates` is rebuilt every render,
		// so depending on it would defeat the memo — and a fresh array on every render makes
		// the ECharts consumers restart their draw-in.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [query.dataUpdatedAt, dateKey, days, allSettled]);

	const { rows, campaigns } = derived;

	return {
		rows,
		campaigns,
		dates: derived.dates,
		truncated: !days && dates.length >= MAX_BU_DAYS,
		isLoading: query.isLoading,
		error: query.error ?? null,
		refetch: () => query.refetch(),
	};
};

/**
 * Every campaign on the account for the selected window, in one request.
 *
 * The whole set is fetched at once so that every column can be sorted. Server-side paging
 * limits sorting to the four keys the endpoint supports, leaving add-to-carts, units, ACoS,
 * AOV, CPM and utilisation unsortable, because ordering one page of twenty says nothing
 * about the other 240 rows.
 *
 * The endpoint's ceiling is 500 and this account has 260 campaigns, so a single call covers
 * it and the sorting happens in the browser. `complete` reports whether that held; above 500
 * campaigns the caller must fall back to the endpoint's own sorting rather than silently
 * ordering a subset.
 */
export const useAllCampaigns = () => {
	const { activeClientId } = useClient();
	const { selected, ready } = useMarketplaces();
	const { range } = useDateRange();

	const query = useQuery({
		queryKey: ["ads-campaigns-all", activeClientId, range, selected],
		queryFn: () =>
			getCampaigns(activeClientId, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				page: 1,
				limit: 500,
				// Insights shows no automation controls (A3, 2026-10-08).
				automation: false,
			}),
		enabled: Boolean(activeClientId) && ready,
		staleTime: 5 * 60 * 1000,
	});

	const items = query.data?.items ?? [];
	const total = query.data?.total ?? 0;

	// Counts per STATE (running / paused / held / ended / draft) come from the same rows, so
	// the filter's labels cost no extra call. The state, not the raw status: each marketplace
	// has its own words (Zepto PAUSED, Blinkit STOPPED), and a filter of one marketplace's
	// words could not find the other's campaigns.
	const counts = {};
	for (const c of items) {
		if (!c.state) continue;
		counts[c.state] = (counts[c.state] ?? 0) + 1;
	}

	return {
		items,
		total,
		counts,
		// Until the tally lands every status would read "0", which is a claim, not a blank.
		ready: !query.isLoading && Boolean(query.data),
		complete: items.length >= total,
		isLoading: query.isLoading,
		error: query.error ?? null,
		refetch: query.refetch,
	};
};
