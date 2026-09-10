import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import {
	addBudgetRule,
	createBidRule,
	createBudgetSchedule,
	deleteBidRule,
	deleteBudgetRule,
	deleteBudgetSchedule,
	getAdvertiser,
	getBidContext,
	getCities,
	getBidRules,
	getBudgetSchedules,
	getCampaignKeywords,
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
	runEngine,
	setActivationNow,
	setAdvertiser,
	setBidState,
	setBudgetNow,
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

export const useHistory = (page = 1, kind) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [HISTORY, activeClientId, page, kind ?? "all"],
		queryFn: () => getHistory(activeClientId, { page, kind }),
		enabled: Boolean(activeClientId),
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

export const useCampaignKeywords = (campaignId) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "keywords", campaignId],
		queryFn: () => getCampaignKeywords(activeClientId, campaignId),
		enabled: Boolean(activeClientId && campaignId),
		staleTime: 5 * 60 * 1000,
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

export const useJob = (jobId) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["auto-job", activeClientId, jobId],
		queryFn: () => getJob(activeClientId, jobId),
		enabled: Boolean(activeClientId && jobId),
		refetchInterval: (query) => {
			const s = query.state.data?.status;
			return s === "success" || s === "failed" ? false : 1500;
		},
	});
};

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
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (scheduleId) =>
			resetBudgetSchedule(activeClientId, scheduleId),
		onSuccess: invalidate,
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
	const invalidate = useInvalidate(BID_RULES);
	return useMutation({
		mutationFn: (ruleId) => deleteBidRule(activeClientId, ruleId),
		onSuccess: invalidate,
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

export const useSetBudgetNow = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: (body) => setBudgetNow(activeClientId, body),
	});
};

export const useSetActivationNow = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: ({ campaignId, ...body }) =>
			setActivationNow(activeClientId, campaignId, body),
	});
};

export const useRefreshCampaigns = () => {
	const { activeClientId } = useClient();
	return useMutation({ mutationFn: () => refreshCampaigns(activeClientId) });
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

export const useRunEngine = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: (which) => runEngine(activeClientId, which),
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

/** The shared city list. Global reference data, so it is cached for the session. */
export const useCities = () =>
	useQuery({
		queryKey: ["reference-cities"],
		queryFn: getCities,
		staleTime: Infinity,
	});
