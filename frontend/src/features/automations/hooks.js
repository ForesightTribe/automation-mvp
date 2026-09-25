import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { invalidateCampaignData } from "../../lib/campaignData";
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
	getBidRules,
	getBudgetSchedules,
	getKeywordMetricsPage,
	getCatalogKeywords,
	getLive,
	getKeywordMetricsRest,
	getCampaignNames,
	getCampaignsForRange,
	getKeywordMetrics,
	getCampaigns,
	getHistory,
	getJob,
	getRecentActions,
	getRunOutcome,
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

export const useBudgetSchedules = () => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [SCHEDULES, activeClientId, mp],
		queryFn: () => getBudgetSchedules(activeClientId, mp),
		enabled: ready,
	});
};

export const useBidRules = () => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [BID_RULES, activeClientId, mp],
		queryFn: () => getBidRules(activeClientId, mp),
		enabled: ready,
	});
};

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

export const useCampaigns = () => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp],
		queryFn: () => getCampaigns(activeClientId, mp),
		enabled: ready,
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
	const { activeClientId, mp, ready } = useScope();
	const { days } = useDateRange();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp, "range", days],
		queryFn: () => getCampaignsForRange(activeClientId, mp, days),
		enabled: ready,
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
export const useAllKeywordMetrics = () => {
	const { activeClientId, mp, ready } = useScope();
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
 * code as Blinkit's performance rows. It carries the live `bid` and the floor `min_bid`
 * instead of spend and ROAS — Zepto has no per-campaign keyword metrics to show.
 */
export const useCatalogKeywords = ({ enabled = true } = {}) => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp, "catalog-keywords"],
		queryFn: () => getCatalogKeywords(activeClientId, mp),
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
 * account now says is the only reliable answer — which is also why `useRunOutcome` below
 * exists rather than trusting `status: success`.
 */
export const useJob = (jobId) => {
	const { activeClientId, mp, ready } = useScope();
	const qc = useQueryClient();
	return useQuery({
		queryKey: ["auto-job", activeClientId, mp, jobId],
		queryFn: async () => {
			const job = await getJob(activeClientId, mp, jobId);
			if (job.status === "success" || job.status === "failed") {
				invalidateCampaignData(qc, activeClientId);
				qc.invalidateQueries({ queryKey: [HISTORY, activeClientId] });
			}
			return job;
		},
		enabled: Boolean(ready && jobId),
		refetchInterval: (query) => {
			const s = query.state.data?.status;
			return s === "success" || s === "failed" ? false : 1500;
		},
	});
};

/**
 * What this client has recently asked for, newest first — the activity list.
 *
 * Polls only while something is unfinished, and stops as soon as everything has settled:
 * an idle dashboard makes no requests at all. 2s rather than the job poller's 1.5s because
 * this is a list someone glances at, not a spinner they are watching.
 *
 * `ACTIVE` is what the badge counts and what keeps the poll alive.
 */
export const ACTIVE_JOB_STATUSES = new Set(["pending", "running"]);

export const useRecentActions = () => {
	const { activeClientId, mp, ready } = useScope();
	const qc = useQueryClient();
	const settled = useRef(new Set());
	return useQuery({
		queryKey: ["auto-actions", activeClientId, mp],
		queryFn: async () => {
			const actions = (await getRecentActions(activeClientId, mp)) ?? [];
			// The moment an action finishes, every screen's campaign data is out of date.
			// Done here as well as in `useJob` because this list outlives the component
			// that started the job: reload the page mid-run and nothing else is watching,
			// so without this the tables would keep serving pre-write values.
			const done = actions.filter(
				(a) => !ACTIVE_JOB_STATUSES.has(a.status),
			);
			const fresh = done.filter((a) => !settled.current.has(a.id));
			for (const a of done) settled.current.add(a.id);
			if (fresh.length) {
				invalidateCampaignData(qc, activeClientId);
				qc.invalidateQueries({ queryKey: [HISTORY, activeClientId] });
			}
			return actions;
		},
		enabled: ready,
		refetchInterval: (query) =>
			(query.state.data ?? []).some((a) =>
				ACTIVE_JOB_STATUSES.has(a.status),
			)
				? 2000
				: false,
	});
};

/**
 * Which of your in-flight actions, if any, is acting on a given row.
 *
 * One definition rather than one per surface, because "is this row busy" has to mean the
 * same thing in the automations table and in the wizard's campaign picker — and getting it
 * subtly different in two places is how a control ends up clickable during the write it
 * would conflict with.
 *
 * The match is deliberately narrow:
 *
 *   - a KEYWORD action (a bid reset) carries its keyword, so it marks only that rule busy.
 *     Matching on the campaign alone would freeze every bid rule on a campaign because one
 *     of its keywords was being reset.
 *   - a CAMPAIGN action (budget, start/stop) marks only campaign-kind rows. A budget write
 *     does not touch a keyword's bid, so its rules stay usable.
 *
 * Returns the action, so a caller can name what is happening rather than only that
 * something is.
 */
export const useActiveActionFor = () => {
	const { data: actions } = useRecentActions();
	const live = useMemo(
		() => (actions ?? []).filter((a) => ACTIVE_JOB_STATUSES.has(a.status)),
		[actions],
	);
	return (row) => {
		if (!row?.campaign_id) return null;
		return (
			live.find((a) =>
				a.campaign_id !== row.campaign_id
					? false
					: a.keyword
						? row.kind === "keyword" && row.keyword === a.keyword
						: row.kind === "campaign",
			) ?? null
		);
	};
};

/**
 * Every row one run recorded — what the engine actually did, read once its job has settled.
 *
 * `enabled` is the settled flag on purpose: before then the run has written nothing, and an
 * empty result would be indistinguishable from "it decided to change nothing".
 *
 * Keyed on the RUN, not the campaign. A run id is minted by the queue and travels into the
 * run, so this is an exact match — where "the newest row for this campaign" was a guess
 * that races the parallel cm_bid / cm_ops lanes and cannot describe a multi-campaign run.
 *
 * An EMPTY list is a real answer, not a missing one: the engines deliberately record no
 * row for a tick that changed nothing (docs D6), so zero rows means "nothing needed doing".
 */
export const useRunOutcome = (runId, enabled) => {
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: ["auto-run-outcome", activeClientId, mp, runId],
		queryFn: () => getRunOutcome(activeClientId, mp, runId),
		enabled: Boolean(ready && runId && enabled),
		select: (page) => page?.items ?? [],
		staleTime: 0,
		gcTime: 0,
	});
};

// ── Mutations ────────────────────────────────────────────────────────────────

const useInvalidate = (key) => {
	const { activeClientId, mp } = useScope();
	const qc = useQueryClient();
	return () => qc.invalidateQueries({ queryKey: [key, activeClientId, mp] });
};

export const useCreateBudgetSchedule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (body) => createBudgetSchedule(activeClientId, mp, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBudgetSchedule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ scheduleId, body }) =>
			updateBudgetSchedule(activeClientId, mp, scheduleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBudgetSchedule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (scheduleId) =>
			deleteBudgetSchedule(activeClientId, mp, scheduleId),
		onSuccess: invalidate,
	});
};

export const useAddBudgetRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ scheduleId, body }) =>
			addBudgetRule(activeClientId, mp, scheduleId, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBudgetRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ ruleId, body }) =>
			updateBudgetRule(activeClientId, mp, ruleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBudgetRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (ruleId) => deleteBudgetRule(activeClientId, mp, ruleId),
		onSuccess: invalidate,
	});
};

export const useResetBudgetSchedule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (scheduleId) =>
			resetBudgetSchedule(activeClientId, mp, scheduleId),
		onSuccess: invalidate,
	});
};

export const useCreateBidRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: (body) => createBidRule(activeClientId, mp, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBidRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: ({ ruleId, body }) =>
			updateBidRule(activeClientId, mp, ruleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBidRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: ({ ruleId, reset = false }) =>
			deleteBidRule(activeClientId, mp, ruleId, { reset }),
		onSuccess: invalidate,
	});
};

export const useResetBidRule = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: (ruleId) => resetBidRule(activeClientId, mp, ruleId),
		onSuccess: invalidate,
	});
};

export const useSetBidState = () => {
	const { activeClientId, mp } = useScope();
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: ({ ruleId, action }) =>
			setBidState(activeClientId, mp, ruleId, action),
		onSuccess: invalidate,
	});
};

export const useSetActivationNow = () => {
	const { activeClientId, mp } = useScope();
	return useMutation({
		mutationFn: ({ campaignId, ...body }) =>
			setActivationNow(activeClientId, mp, campaignId, body),
	});
};

export const useRefreshCampaigns = () => {
	const { activeClientId, mp } = useScope();
	return useMutation({
		mutationFn: () => refreshCampaigns(activeClientId, mp),
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
 * own switch (`live_armed`), read from `GET …/{marketplace}/live`.
 *
 * This used to be INFERRED from the last run's `dry_run`, which was wrong for an account
 * armed since its last run and said nothing at all before a first run. The switch itself
 * is armed from the CLI only (`cm arm -m <marketplace>`), never from the dashboard.
 *
 * Returns "live" | "dry" | "unknown".
 */
export const useWriteMode = () => {
	const { activeClientId, mp, ready } = useScope();
	const { data, isLoading, isError } = useQuery({
		queryKey: ["auto-live", activeClientId, mp],
		queryFn: () => getLive(activeClientId, mp),
		enabled: ready,
		staleTime: 5 * 60 * 1000,
	});
	return {
		mode: isError || !data ? "unknown" : data.live ? "live" : "dry",
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
