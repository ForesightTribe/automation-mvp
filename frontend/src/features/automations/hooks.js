import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { invalidateAfterWrite } from "../../lib/campaignData";
import { invalidateRecentActions, pollInterval } from "../../lib/actions";
import { sortRows } from "../../lib/sortRows";

import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useAutomationMarketplace } from "../../context/MarketplaceContext";
import {
	addBudgetRule,
	createBidRule,
	createBudgetSchedule,
	deleteBidRule,
	resetBidRule,
	deleteBudgetRule,
	deleteBudgetSchedule,
	getAdvertiser,
	getBidContext,
	getOverview,
	getKeywordMetricsPage,
	getCatalogKeywords,
	getKeywordMetricsRest,
	getCampaignNames,
	getCampaignsForRange,
	getKeywordMetrics,
	getCampaigns,
	getHistory,
	getJob,
	refreshCampaigns,
	resetBudgetSchedule,
	setActivationNow,
	setAdvertiser,
	setBidState,
	updateBidRule,
	updateBudgetRule,
	updateBudgetSchedule,
} from "./api";

// Own cache namespace ("auto-*"), separate from Campaign Manager v2's ("cm2-*")
// — same backend rows, two independent caches, so neither page's query
// lifecycle can affect the other's.
// Schedules, bid rules, the header's history, the wallet note and the live switch all live
// in ONE cached response (`/overview`); the hooks below each select their part of it, so the
// page opens with one request instead of five.
const OVERVIEW = "auto-overview";
const HISTORY = "auto-history";
const CAMPAIGNS = "auto-campaigns";
const ADVERTISER = "auto-advertiser";

/**
 * Who and WHERE: the active client and the one marketplace the navbar has chosen for the
 * automation pages. Every campaign-manager call names that marketplace (no default, ZC-D1),
 * and every cache key carries it, so switching Blinkit / Zepto shows that marketplace's
 * data and never the other's cached rows. `ready` is false until both are known.
 */
const useScope = () => {
	const { activeClientId } = useClient();
	const { marketplace: mp } = useAutomationMarketplace();
	return { activeClientId, mp, ready: Boolean(activeClientId && mp) };
};

// ── Queries ──────────────────────────────────────────────────────────────────

/**
 * The page's opening data, one request. Every consumer passes a `select`, so each re-renders
 * only when its own part changes, and React Query shares the single fetch between them.
 */
const useOverview = (select, { enabled = true } = {}) => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [OVERVIEW, activeClientId, mp],
		queryFn: () => getOverview(activeClientId, mp),
		enabled: ready && enabled,
		select,
	});
};

const pickSchedules = (d) => d.budget_schedules;
const pickBidRules = (d) => d.bid_rules;
const pickHistory = (d) => ({ items: d.history, total: d.history_total });
const pickWallet = (d) => d.wallet;
const pickLive = (d) => d.live;

export const useBudgetSchedules = () => useOverview(pickSchedules);

export const useBidRules = () => useOverview(pickBidRules);

/** Page 1 of History, changes only — the header's status line. From the overview. */
export const useLatestHistory = () => useOverview(pickHistory);

/** The newest ad-wallet note, or null — the wallet banner. From the overview. */
export const useWalletNote = () => useOverview(pickWallet);

export const useHistory = (page = 1, kind, opts = {}) => {
	const { activeClientId, mp, ready } = useScope();
	const {
		campaignId,
		ruleId,
		keyword,
		success,
		includeUnchanged = false,
		limit,
		enabled = true,
	} = opts;
	return useQuery({
		queryKey: [
			HISTORY,
			activeClientId,
			mp,
			page,
			kind ?? "all",
			campaignId ?? "all",
			ruleId ?? "all",
			keyword ?? "all",
			success ?? "all",
			includeUnchanged,
			limit ?? "default",
		],
		queryFn: () =>
			getHistory(activeClientId, mp, {
				page,
				kind,
				campaignId,
				ruleId,
				keyword,
				success,
				includeUnchanged,
				limit,
			}),
		enabled: ready && enabled,
	});
};

export const useCampaigns = ({ enabled = true } = {}) => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp],
		queryFn: () => getCampaigns(activeClientId, mp),
		enabled: ready && enabled,
		staleTime: 5 * 60 * 1000,
		select: (page) => page?.items ?? [],
	});
};

/** Poll an enqueued job until it terminates — the enqueue→poll UX for
 * "Execution/run details". Stops polling once the job succeeds or fails. */
/**
 * Blinkit's published bid range per keyword, plus the cities the campaign targets.
 * Enabled only once a campaign is chosen — the floors are per campaign+keyword, so
 * there is nothing to ask for before that.
 */
/**
 * Campaigns over the GLOBAL date range, for the detail view. Separate from the name/catalogue
 * queries on purpose: those want a stable list regardless of the picker, this wants numbers
 * that match what the navbar says.
 */
export const useCampaignsForRange = ({ enabled = true } = {}) => {
	const { activeClientId, mp, ready } = useScope();
	const { days } = useDateRange();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp, "range", days],
		queryFn: () => getCampaignsForRange(activeClientId, mp, days),
		enabled: ready && enabled,
		staleTime: 5 * 60 * 1000,
		select: (page) => page?.items ?? [],
	});
};

/** id → name for EVERY campaign, including ones the selectable list filters out. */
export const useCampaignNames = () => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp, "names"],
		queryFn: () => getCampaignNames(activeClientId, mp),
		enabled: ready,
		staleTime: 10 * 60 * 1000,
		select: (page) => page?.items ?? [],
	});
};

/**
 * Every keyword row for the client, in two waves — see api.js for why. `data` is what has
 * arrived so far and `isComplete` says whether the tail is still coming, so the picker can
 * render the top spenders immediately instead of holding a blank screen for ~27s.
 */
export const useAllKeywordMetrics = ({ enabled = true } = {}) => {
	const { activeClientId, mp, ready: scoped } = useScope();
	// Off until something that shows keywords is on screen — the wizard is mounted closed.
	const ready = scoped && enabled;
	// Keyword PERFORMANCE (/ads/keywords) exists on Blinkit only. Every other marketplace's
	// picker reads the campaign catalogue (`useCatalogKeywords`), so these queries stay off
	// there rather than returning an empty list that reads as "no keywords".
	const metrics = ready && mp === "blinkit";
	const first = useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "keyword-metrics", 1],
		queryFn: () => getKeywordMetricsPage(activeClientId, 1),
		enabled: metrics,
		staleTime: 5 * 60 * 1000,
	});
	const pages = first.data?.pages ?? 1;
	const rest = useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "keyword-metrics", "rest", pages],
		queryFn: () => getKeywordMetricsRest(activeClientId, pages),
		enabled: Boolean(metrics && first.data && pages > 1),
		staleTime: 5 * 60 * 1000,
	});
	const catalog = useCatalogKeywords({ enabled: ready && mp !== "blinkit" });
	if (mp !== "blinkit") {
		return {
			data: catalog.data ?? [],
			isLoading: catalog.isLoading,
			isComplete: !catalog.isLoading,
			total: catalog.data?.length ?? 0,
		};
	}
	return {
		data: [...(first.data?.items ?? []), ...(rest.data ?? [])],
		isLoading: first.isLoading,
		isComplete: pages < 2 || Boolean(rest.data),
		total: first.data?.total ?? 0,
	};
};

/**
 * Every keyword the marketplace's campaign CATALOGUE holds, reshaped into the picker's row
 * shape (`campaign_id`, `target`, `match_type`, …) so the picker renders it with the same
 * code as Blinkit's performance rows. It carries the live `bid` and the floor `min_bid`,
 * and on Zepto the keyword's performance over the navbar's dates (`budget_consumed`,
 * `total_sales`, `orders`, …, P43).
 */
export const useCatalogKeywords = ({ enabled = true } = {}) => {
	const { activeClientId, mp, ready } = useScope();
	// The navbar's window: on Zepto the rows carry keyword performance for these dates.
	const { range } = useDateRange();
	return useQuery({
		queryKey: [
			CAMPAIGNS,
			activeClientId,
			mp,
			"catalog-keywords",
			range.from,
			range.to,
		],
		queryFn: () => getCatalogKeywords(activeClientId, mp, range),
		enabled: ready && enabled,
		staleTime: 5 * 60 * 1000,
		select: (rows) =>
			(rows ?? []).map((r) => ({
				...r,
				target: r.keyword,
				target_type: "keyword",
				catalog: true,
			})),
	});
};

export const useKeywordMetrics = (campaignId) => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "keyword-metrics", campaignId],
		queryFn: () => getKeywordMetrics(activeClientId, campaignId),
		// Blinkit's performance table only — see useAllKeywordMetrics.
		enabled: Boolean(ready && mp === "blinkit" && campaignId),
		staleTime: 5 * 60 * 1000,
		select: (page) => page?.items ?? [],
	});
};

export const useBidContext = (campaignId) => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp, "bid-context", campaignId],
		queryFn: () => getBidContext(activeClientId, mp, campaignId),
		enabled: Boolean(ready && campaignId),
		staleTime: 5 * 60 * 1000,
	});
};

export const useAdvertiser = () => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [ADVERTISER, activeClientId, mp],
		queryFn: () => getAdvertiser(activeClientId, mp),
		enabled: ready,
	});
};

/**
 * Poll one enqueued job until it settles, then mark every screen's campaign data stale.
 *
 * ⚠️ The invalidation lives HERE and not on the mutations, because these writes happen on
 * the VM. A mutation resolving means "the job was queued", nothing more — invalidating
 * there would refetch the value as it was BEFORE the write and cache it as fresh, which is
 * worse than not invalidating at all. The job settling is the first moment the catalogue
 * can actually have changed.
 *
 * Invalidates rather than patches: the engine runs its own guardrails against a fresh
 * read, so a job can settle having done something other than what was asked. What the
 * account now says is the only reliable answer — which is also why `useRunOutcome`
 * (lib/actions.js) exists rather than trusting `status: success`.
 */
export const useJob = (jobId) => {
	const { activeClientId, mp, ready } = useScope();
	const qc = useQueryClient();
	return useQuery({
		queryKey: ["auto-job", activeClientId, mp, jobId],
		queryFn: async () => {
			const job = await getJob(activeClientId, mp, jobId);
			if (job.status === "success" || job.status === "failed") {
				invalidateAfterWrite(qc, activeClientId);
			}
			return job;
		},
		enabled: Boolean(ready && jobId),
		// The same back-off as the recent-actions list (`pollInterval`): fast while the job is
		// fresh, slower once it is plainly waiting in the queue, and stopped the moment it
		// settles. A fixed 1.5s cost ~200 requests for one job that waited five minutes.
		// Before the first fetch there is no job yet, so poll at the fast rate.
		refetchInterval: (query) =>
			query.state.data ? pollInterval([query.state.data]) : 1500,
	});
};

// Recent actions, row matching and run outcomes live in lib/actions.js — One-time Ops
// needs the same answers and may not import from this feature.

// ── Mutations ────────────────────────────────────────────────────────────────

const useInvalidate = (key) => {
	const { activeClientId, mp } = useScope();
	const qc = useQueryClient();
	return () => qc.invalidateQueries({ queryKey: [key, activeClientId, mp] });
};

export const useCreateBudgetSchedule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: (body) => createBudgetSchedule(activeClientId, mp, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBudgetSchedule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: ({ scheduleId, body }) =>
			updateBudgetSchedule(activeClientId, mp, scheduleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBudgetSchedule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: (scheduleId) =>
			deleteBudgetSchedule(activeClientId, mp, scheduleId),
		onSuccess: invalidate,
	});
};

export const useAddBudgetRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: ({ scheduleId, body }) =>
			addBudgetRule(activeClientId, mp, scheduleId, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBudgetRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: ({ ruleId, body }) =>
			updateBudgetRule(activeClientId, mp, ruleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBudgetRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: (ruleId) => deleteBudgetRule(activeClientId, mp, ruleId),
		onSuccess: invalidate,
	});
};

export const useResetBudgetSchedule = () => {
	const { activeClientId, mp } = useScope();
	const qc = useQueryClient();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: (scheduleId) =>
			resetBudgetSchedule(activeClientId, mp, scheduleId),
		onSuccess: () => {
			invalidate();
			invalidateRecentActions(qc, activeClientId);
		},
	});
};

export const useCreateBidRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: (body) => createBidRule(activeClientId, mp, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBidRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: ({ ruleId, body }) =>
			updateBidRule(activeClientId, mp, ruleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBidRule = () => {
	const { activeClientId, mp } = useScope();
	const qc = useQueryClient();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: ({ ruleId, reset = false }) =>
			deleteBidRule(activeClientId, mp, ruleId, { reset }),
		// Delete-with-reset enqueues a bid write; a plain delete enqueues nothing, and the
		// extra refetch costs one small request.
		onSuccess: () => {
			invalidate();
			invalidateRecentActions(qc, activeClientId);
		},
	});
};

export const useResetBidRule = () => {
	const { activeClientId, mp } = useScope();
	const qc = useQueryClient();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: (ruleId) => resetBidRule(activeClientId, mp, ruleId),
		onSuccess: () => {
			invalidate();
			invalidateRecentActions(qc, activeClientId);
		},
	});
};

export const useSetBidState = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(OVERVIEW);
	return useMutation({
		mutationFn: ({ ruleId, action }) =>
			setBidState(activeClientId, mp, ruleId, action),
		onSuccess: invalidate,
	});
};

export const useSetActivationNow = () => {
	const { activeClientId, mp } = useScope();
	const qc = useQueryClient();
	return useMutation({
		mutationFn: ({ campaignId, ...body }) =>
			setActivationNow(activeClientId, mp, campaignId, body),
		onSuccess: () => invalidateRecentActions(qc, activeClientId),
	});
};

export const useRefreshCampaigns = () => {
	const { activeClientId, mp } = useScope();
	const qc = useQueryClient();
	return useMutation({
		mutationFn: () => refreshCampaigns(activeClientId, mp),
		onSuccess: () => invalidateRecentActions(qc, activeClientId),
	});
};

export const useUpdateAdvertiser = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(ADVERTISER);
	return useMutation({
		mutationFn: (advertiserId) =>
			setAdvertiser(activeClientId, mp, advertiserId),
		onSuccess: invalidate,
	});
};

/**
 * Whether this marketplace's automations actually write, or only simulate — the engine's
 * own switch (`live_armed`), carried on the page's overview (no request of its own).
 *
 * This used to be INFERRED from the last run's `dry_run`, which was wrong for an account
 * armed since its last run and said nothing at all before a first run. The switch itself
 * is armed from the CLI only (`cm arm -m <marketplace>`), never from the dashboard.
 *
 * Returns "live" | "dry" | "unknown".
 */
export const useWriteMode = ({ enabled = true } = {}) => {
	const { data, isLoading, isError } = useOverview(pickLive, { enabled });
	return {
		mode: isError || data == null ? "unknown" : data ? "live" : "dry",
		isLoading,
	};
};

/**
 * ⚠️ There is no `useCities` here any more, deliberately (2026-09-15).
 *
 * The wizard used to read the store catalogue for its own city list while `bid-context`
 * supplied the campaign's targeted cities, and the picker chose between them by list
 * length — which is also what "still loading" looks like. A sorted catalogue rendered
 * first and was replaced a second later by an unsorted, differently-spelled list.
 *
 * `bid-context` now answers the whole question — the campaign's cities when it targets
 * some, every measurable city when it does not — so the form has ONE source. Reintroducing
 * a second one brings the swap back.
 */

/**
 * Click-to-sort over rows already in hand, for the wizard's picker tables.
 *
 * Keys are STRINGS deliberately: an inline accessor is a new function identity on every
 * render, so comparing keys by function never matches and clicking a column could never
 * toggle its direction. Clicking the active column flips it; clicking another starts that
 * one descending, which is what a reader means by "sort by spend".
 */
export const useTableSort = (
	rows,
	accessors,
	initialKey,
	initialOrder = "desc",
) => {
	const [sort, setSort] = useState(initialKey);
	const [order, setOrder] = useState(initialOrder);
	const sorted = useMemo(
		// eslint-disable-next-line react-hooks/exhaustive-deps
		() => sortRows(rows, accessors[sort], order),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[rows, sort, order],
	);
	const onSort = (key) => {
		if (key === sort)
			return setOrder((o) => (o === "desc" ? "asc" : "desc"));
		setSort(key);
		setOrder("desc");
	};
	return { sorted, sort, order, onSort };
};
