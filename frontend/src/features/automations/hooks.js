import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { invalidateAfterWrite } from "../../lib/campaignData";
import { invalidateRecentActions, pollInterval } from "../../lib/actions";
import { sortRows } from "../../lib/sortRows";

import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
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
	getBidRules,
	getBudgetSchedules,
	getKeywordMetricsPage,
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
const SCHEDULES = "auto-budget-schedules";
const BID_RULES = "auto-bid-rules";
const HISTORY = "auto-history";
const CAMPAIGNS = "auto-campaigns";
const ADVERTISER = "auto-advertiser";

// ── Queries ──────────────────────────────────────────────────────────────────

export const useBudgetSchedules = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [SCHEDULES, activeClientId],
		queryFn: () => getBudgetSchedules(activeClientId),
		enabled: Boolean(activeClientId),
	});
};

export const useBidRules = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [BID_RULES, activeClientId],
		queryFn: () => getBidRules(activeClientId),
		enabled: Boolean(activeClientId),
	});
};

export const useHistory = (page = 1, kind, opts = {}) => {
	const { activeClientId } = useClient();
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
			getHistory(activeClientId, {
				page,
				kind,
				campaignId,
				ruleId,
				keyword,
				success,
				includeUnchanged,
				limit,
			}),
		enabled: Boolean(activeClientId) && enabled,
	});
};

export const useCampaigns = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId],
		queryFn: () => getCampaigns(activeClientId),
		enabled: Boolean(activeClientId),
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
export const useCampaignsForRange = () => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "range", days],
		queryFn: () => getCampaignsForRange(activeClientId, days),
		enabled: Boolean(activeClientId),
		staleTime: 5 * 60 * 1000,
		select: (page) => page?.items ?? [],
	});
};

/** id → name for EVERY campaign, including ones the selectable list filters out. */
export const useCampaignNames = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "names"],
		queryFn: () => getCampaignNames(activeClientId),
		enabled: Boolean(activeClientId),
		staleTime: 10 * 60 * 1000,
		select: (page) => page?.items ?? [],
	});
};

/**
 * Every keyword row for the client, in two waves — see api.js for why. `data` is what has
 * arrived so far and `isComplete` says whether the tail is still coming, so the picker can
 * render the top spenders immediately instead of holding a blank screen for ~27s.
 */
export const useAllKeywordMetrics = () => {
	const { activeClientId } = useClient();
	const first = useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "keyword-metrics", 1],
		queryFn: () => getKeywordMetricsPage(activeClientId, 1),
		enabled: Boolean(activeClientId),
		staleTime: 5 * 60 * 1000,
	});
	const pages = first.data?.pages ?? 1;
	const rest = useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "keyword-metrics", "rest", pages],
		queryFn: () => getKeywordMetricsRest(activeClientId, pages),
		enabled: Boolean(activeClientId && first.data && pages > 1),
		staleTime: 5 * 60 * 1000,
	});
	return {
		data: [...(first.data?.items ?? []), ...(rest.data ?? [])],
		isLoading: first.isLoading,
		isComplete: pages < 2 || Boolean(rest.data),
		total: first.data?.total ?? 0,
	};
};

export const useKeywordMetrics = (campaignId) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "keyword-metrics", campaignId],
		queryFn: () => getKeywordMetrics(activeClientId, campaignId),
		enabled: Boolean(activeClientId && campaignId),
		staleTime: 5 * 60 * 1000,
		select: (page) => page?.items ?? [],
	});
};

export const useBidContext = (campaignId) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "bid-context", campaignId],
		queryFn: () => getBidContext(activeClientId, campaignId),
		enabled: Boolean(activeClientId && campaignId),
		staleTime: 5 * 60 * 1000,
	});
};

export const useAdvertiser = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [ADVERTISER, activeClientId],
		queryFn: () => getAdvertiser(activeClientId),
		enabled: Boolean(activeClientId),
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
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	return useQuery({
		queryKey: ["auto-job", activeClientId, jobId],
		queryFn: async () => {
			const job = await getJob(activeClientId, jobId);
			if (job.status === "success" || job.status === "failed") {
				invalidateAfterWrite(qc, activeClientId);
			}
			return job;
		},
		enabled: Boolean(activeClientId && jobId),
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
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	return () => qc.invalidateQueries({ queryKey: [key, activeClientId] });
};

export const useCreateBudgetSchedule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (body) => createBudgetSchedule(activeClientId, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBudgetSchedule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ scheduleId, body }) =>
			updateBudgetSchedule(activeClientId, scheduleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBudgetSchedule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (scheduleId) =>
			deleteBudgetSchedule(activeClientId, scheduleId),
		onSuccess: invalidate,
	});
};

export const useAddBudgetRule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ scheduleId, body }) =>
			addBudgetRule(activeClientId, scheduleId, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBudgetRule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ ruleId, body }) =>
			updateBudgetRule(activeClientId, ruleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBudgetRule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (ruleId) => deleteBudgetRule(activeClientId, ruleId),
		onSuccess: invalidate,
	});
};

export const useResetBudgetSchedule = () => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (scheduleId) =>
			resetBudgetSchedule(activeClientId, scheduleId),
		onSuccess: () => {
			invalidate();
			invalidateRecentActions(qc, activeClientId);
		},
	});
};

export const useCreateBidRule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: (body) => createBidRule(activeClientId, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBidRule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: ({ ruleId, body }) =>
			updateBidRule(activeClientId, ruleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBidRule = () => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: ({ ruleId, reset = false }) =>
			deleteBidRule(activeClientId, ruleId, { reset }),
		// Delete-with-reset enqueues a bid write; a plain delete enqueues nothing, and the
		// extra refetch costs one small request.
		onSuccess: () => {
			invalidate();
			invalidateRecentActions(qc, activeClientId);
		},
	});
};

export const useResetBidRule = () => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: (ruleId) => resetBidRule(activeClientId, ruleId),
		onSuccess: () => {
			invalidate();
			invalidateRecentActions(qc, activeClientId);
		},
	});
};

export const useSetBidState = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: ({ ruleId, action }) =>
			setBidState(activeClientId, ruleId, action),
		onSuccess: invalidate,
	});
};

export const useSetActivationNow = () => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	return useMutation({
		mutationFn: ({ campaignId, ...body }) =>
			setActivationNow(activeClientId, campaignId, body),
		onSuccess: () => invalidateRecentActions(qc, activeClientId),
	});
};

export const useRefreshCampaigns = () => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	return useMutation({
		mutationFn: () => refreshCampaigns(activeClientId),
		onSuccess: () => invalidateRecentActions(qc, activeClientId),
	});
};

export const useUpdateAdvertiser = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(ADVERTISER);
	return useMutation({
		mutationFn: (advertiserId) =>
			setAdvertiser(activeClientId, advertiserId),
		onSuccess: invalidate,
	});
};

/**
 * Whether this account's automations are actually writing to Blinkit, or only simulating.
 *
 * ⚠️ INFERRED, and labelled as such wherever it is shown. The engine is dry-run by default
 * and armed per tenant (`live_armed` on `cm_platform_accounts`), but no endpoint reports that
 * flag: `dry_run` exists only on records of runs that already happened. So this reads the
 * most recent run and reports what the engine did last time.
 *
 * That is weaker than asking the engine directly, and it is wrong in one case: an account
 * armed since its last run still reads as simulating. It is still worth showing, because the
 * alternative is a create screen that says "this will act on your live account" without
 * knowing whether that is true.
 *
 * Returns "live" | "dry" | "unknown".
 */
export const useWriteMode = () => {
	const { activeClientId } = useClient();
	const { data, isLoading } = useQuery({
		queryKey: [HISTORY, activeClientId, "write-mode"],
		queryFn: () => getHistory(activeClientId, { page: 1, limit: 5 }),
		enabled: Boolean(activeClientId),
		staleTime: 5 * 60 * 1000,
	});
	const rows = data?.items ?? [];
	return {
		mode: !rows.length
			? "unknown"
			: rows.some((r) => r.dry_run === false)
				? "live"
				: "dry",
		since: rows[0]?.timestamp ?? null,
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
