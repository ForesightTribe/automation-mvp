/**
 * Insights: React Query hooks.
 *
 * Re-exported from the Ads feature for the same reason as api.js: identical contract, so
 * sharing the module also shares the query cache. That is deliberate while both pages
 * exist, because the same numbers rendered twice must not disagree.
 */
export * from "../ads/hooks";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import { getCampaigns, getPerformance, getBudgetSplit } from "../ads/api";

/**
 * The window immediately before the selected one, of the same length.
 *
 * "Is this good?" is unanswerable from one number, so every comparison here is against the
 * period that just ended rather than an arbitrary baseline: a 30-day view compares with the
 * 30 days before it, and changing the picker moves both windows together.
 */
export const usePreviousRange = () => {
	const { range } = useDateRange();
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

/** Daily rows for the previous window. Only fetched once a comparison is opened. */
export const usePreviousPerformance = (enabled = false) => {
	const { activeClientId } = useClient();
	const { selected } = useMarketplaces();
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
		enabled: Boolean(activeClientId && enabled),
		staleTime: 5 * 60 * 1000,
	});
};

/** Spend split for the previous window, for the same reason. */
export const usePreviousBudgetSplit = (enabled = false) => {
	const { activeClientId } = useClient();
	const { selected } = useMarketplaces();
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
		enabled: Boolean(activeClientId && enabled),
		staleTime: 5 * 60 * 1000,
	});
};

import { useMutation } from "@tanstack/react-query";
import { setCampaignActivation, setCampaignBudget } from "./api";

/** Start or stop one campaign now. Returns the job id to poll. */
export const useSetCampaignActivation = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: ({ campaignId, status }) =>
			setCampaignActivation(activeClientId, campaignId, status),
	});
};

/** Push a budget to one campaign now. Also returns a job id. */
export const useSetCampaignBudget = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: ({ campaignId, budget }) =>
			setCampaignBudget(activeClientId, campaignId, budget),
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

/**
 * How many day-queries may be in flight at once.
 *
 * ⚠️ Not a nicety. `useQueries` fires every query the moment it is enabled, so an unstaged
 * 31-day drawer opens 31 requests at once against an API whose connection pool holds 10.
 * That exhausts the pool: every later request, `/auth/me` included, queues and then fails
 * with "QueuePool limit of size 10 reached". A read-only chart must not be able to take the
 * API down, so the days are drawn a few at a time.
 */
const BU_CONCURRENCY = 4;

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

export const useDailyBudgetUtilisation = ({
	enabled = true,
	days = null,
} = {}) => {
	const { activeClientId } = useClient();
	const { selected } = useMarketplaces();
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

	// How many days have come back. Each batch that settles releases the next, so the
	// requests walk the window instead of arriving all at once.
	//
	// ⚠️ The counter resets whenever the QUESTION changes — a different client, a different
	// marketplace filter, a different window. It only climbs while one set of days loads,
	// so carrying its previous high into a new set makes the gate
	// `i < settled + BU_CONCURRENCY` release every day at once: a dozen requests against a
	// pool of ten, where the days that lose the race come back empty.
	const [settled, setSettled] = useState(0);
	const question = `${activeClientId}|${selected.join(",")}|${dates.join(",")}|${enabled}`;
	const asked = useRef(question);
	// ⚠️ The gate is recomputed DURING render, not reset in an effect. `useQueries` fires on
	// commit, so an effect that zeroes the counter afterwards runs too late: the render that
	// first sees the new question has already enabled every day against the old high-water
	// mark and sent them. Reading 0 for that render is what actually holds the batch.
	const gate = asked.current === question ? settled : 0;
	useEffect(() => {
		asked.current = question;
		setSettled(0);
	}, [question]);

	const results = useQueries({
		queries: dates.map((date, i) => ({
			queryKey: ["ads-bu-day", activeClientId, selected, date],
			queryFn: () =>
				getCampaigns(activeClientId, {
					start: date,
					end: date,
					marketplaces: selected,
					page: 1,
					// The account's whole campaign list, which is what a day's spend is spread over.
					limit: 500,
				}),
			enabled:
				enabled && Boolean(activeClientId) && i < gate + BU_CONCURRENCY,
			// A past day never changes once its scrape has landed, so this is cheap to hold.
			staleTime: 15 * 60 * 1000,
		})),
	});

	/**
	 * ⚠️ Memoised on the queries' own update stamps, not left to rebuild each render.
	 *
	 * Consumers feed these arrays to ECharts, and EChart re-applies its option whenever the
	 * option's identity changes. A fresh array on every render restarts the draw-in on every
	 * render, so the chart snaps to its final frame instead of animating. The stamps change
	 * only when data actually lands, which is exactly when the derivation should run again.
	 */
	const stamp = results.map((r) => r.dataUpdatedAt ?? 0).join(",");
	const done = results.filter((r) => r.isSuccess || r.isError).length;
	useEffect(() => {
		if (asked.current !== question) return;
		setSettled((n) => (done > n ? done : n));
	}, [done, question]);

	const dateKey = dates.join(",");
	// eslint-disable-next-line react-hooks/exhaustive-deps
	const allSettled = done === dates.length;
	const derived = useMemo(() => {
		const all = dates.map((date, i) => {
			const items = results[i].data?.items ?? [];
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
		// zero spend, so they are dropped rather than drawn as a floor.
		//
		// ⚠️ Only once every day has answered. The requests arrive in batches, so mid-flight
		// the newest days look empty simply because they have not returned yet; trimming then
		// left a "7 day" strip rendering five dots that grew as the data landed.
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
		 * Built from the responses already in hand, so it costs no extra request. A campaign
		 * appears if it spent on ANY day in the window; days it did not run stay null rather
		 * than zero, because "did not run" and "ran and spent nothing" are different facts
		 * and only one of them is a utilisation failure.
		 */
		const byCampaign = new Map();
		kept.forEach((date, di) => {
			const items = results[start + di].data?.items ?? [];
			for (const c of items) {
				if (!((c.budget_consumed ?? 0) > 0) || !c.daily_budget)
					continue;
				if (!byCampaign.has(c.campaign_id)) {
					byCampaign.set(c.campaign_id, {
						campaign_id: c.campaign_id,
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
				const row = byCampaign.get(c.campaign_id);
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
		// `stamp` and `dateKey` ARE the dependencies: `results` and `dates` are rebuilt on
		// every render by useQueries, so depending on them would defeat the memo entirely.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [stamp, dateKey, days, allSettled]);

	const { rows, campaigns } = derived;

	return {
		rows,
		campaigns,
		dates: derived.dates,
		truncated: !days && dates.length >= MAX_BU_DAYS,
		isLoading: results.some((r) => r.isLoading),
		error: results.find((r) => r.error)?.error ?? null,
		refetch: () => results.forEach((r) => r.refetch()),
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
	const { selected } = useMarketplaces();
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
			}),
		enabled: Boolean(activeClientId),
		staleTime: 5 * 60 * 1000,
	});

	const items = query.data?.items ?? [];
	const total = query.data?.total ?? 0;

	// Counts per status come from the same rows, so the filter's labels cost no extra call.
	const counts = {};
	for (const c of items) {
		if (!c.status) continue;
		counts[c.status] = (counts[c.status] ?? 0) + 1;
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
