import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import {
	addBudgetRule,
	createBidRule,
	createBudgetSchedule,
	deleteBidRule,
	deleteBudgetRule,
	deleteBudgetSchedule,
	getAdvertiser,
	getBidRules,
	getBudgetSchedules,
	getCampaignKeywords,
	getCampaigns,
	getHistory,
	getJob,
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

const SCHEDULES = "cm2-budget-schedules";
const BID_RULES = "cm2-bid-rules";
const HISTORY = "cm2-history";
const ADVERTISER = "cm2-advertiser";
const CAMPAIGNS = "cm2-campaigns";

// ── Queries ─────────────────────────────────────────────────────────────────

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

export const useAdvertiser = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [ADVERTISER, activeClientId],
		queryFn: () => getAdvertiser(activeClientId),
		enabled: Boolean(activeClientId),
	});
};

/** Campaign catalogue for the name/id pickers — cached a while, it rarely changes. */
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

/** Keywords already on a campaign — powers the bid form's keyword suggestions. */
export const useCampaignKeywords = (campaignId) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, "keywords", campaignId],
		queryFn: () => getCampaignKeywords(activeClientId, campaignId),
		enabled: Boolean(activeClientId && campaignId),
		staleTime: 5 * 60 * 1000,
	});
};

/**
 * Poll a single enqueued job until it terminates (the enqueue→poll UX). The
 * interval stops itself once the job reaches success/failed, so the spinner
 * resolves to a real outcome instead of a blind setTimeout.
 */
export const useJob = (jobId) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["cm2-job", activeClientId, jobId],
		queryFn: () => getJob(activeClientId, jobId),
		enabled: Boolean(activeClientId && jobId),
		refetchInterval: (query) => {
			const s = query.state.data?.status;
			return s === "success" || s === "failed" ? false : 1500;
		},
	});
};

// ── Mutations ───────────────────────────────────────────────────────────────

const useInvalidate = (key) => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	return () => qc.invalidateQueries({ queryKey: [key, activeClientId] });
};

/**
 * Optimistic list mutation: apply `updater(current, vars)` to the cached list before the
 * request resolves so the card reflects the change instantly, roll back on error, and
 * invalidate on settle to reconcile with the server. Fixes the "list only updates on a
 * full refresh" lag on delete / pause / stop / reset.
 */
const useOptimistic = (queryKeyName, mutationFn, updater) => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	const key = [queryKeyName, activeClientId];
	return useMutation({
		mutationFn: (vars) => mutationFn(activeClientId, vars),
		onMutate: async (vars) => {
			await qc.cancelQueries({ queryKey: key });
			const prev = qc.getQueryData(key);
			qc.setQueryData(key, (old) => updater(old ?? [], vars));
			return { prev };
		},
		onError: (_e, _v, ctx) => {
			if (ctx?.prev !== undefined) qc.setQueryData(key, ctx.prev);
		},
		onSettled: () => qc.invalidateQueries({ queryKey: key }),
	});
};

const BID_STATE = { pause: "paused", resume: "active", stop: "stopped" };

export const useCreateBudgetSchedule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: (body) => createBudgetSchedule(activeClientId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBudgetSchedule = () =>
	useOptimistic(SCHEDULES, deleteBudgetSchedule, (list, scheduleId) =>
		list.filter((s) => s.id !== scheduleId),
	);

export const useAddBudgetRule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ scheduleId, body }) => addBudgetRule(activeClientId, scheduleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBudgetRule = () =>
	useOptimistic(SCHEDULES, deleteBudgetRule, (list, ruleId) =>
		list.map((s) => ({ ...s, rules: s.rules.filter((r) => r.id !== ruleId) })),
	);

export const useResetBudgetSchedule = () =>
	useOptimistic(SCHEDULES, resetBudgetSchedule, (list, scheduleId) =>
		list.map((s) => (s.id === scheduleId ? { ...s, state: "stopped" } : s)),
	);

export const useUpdateBudgetSchedule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ scheduleId, body }) => updateBudgetSchedule(activeClientId, scheduleId, body),
		onSuccess: invalidate,
	});
};

export const useUpdateBudgetRule = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(SCHEDULES);
	return useMutation({
		mutationFn: ({ ruleId, body }) => updateBudgetRule(activeClientId, ruleId, body),
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
		mutationFn: ({ ruleId, body }) => updateBidRule(activeClientId, ruleId, body),
		onSuccess: invalidate,
	});
};

export const useDeleteBidRule = () =>
	useOptimistic(BID_RULES, deleteBidRule, (list, ruleId) =>
		list.filter((r) => r.id !== ruleId),
	);

export const useSetBidState = () =>
	useOptimistic(
		BID_RULES,
		(clientId, { ruleId, action }) => setBidState(clientId, ruleId, action),
		(list, { ruleId, action }) =>
			list.map((r) => (r.id === ruleId ? { ...r, state: BID_STATE[action] ?? r.state } : r)),
	);

export const useSetBudgetNow = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: (body) => setBudgetNow(activeClientId, body),
	});
};

export const useSetActivationNow = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: ({ campaignId, ...body }) => setActivationNow(activeClientId, campaignId, body),
	});
};

export const useRunEngine = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: (which) => runEngine(activeClientId, which),
	});
};

export const useSetAdvertiser = () => {
	const { activeClientId } = useClient();
	const invalidate = useInvalidate(ADVERTISER);
	return useMutation({
		mutationFn: (advertiserId) => setAdvertiser(activeClientId, advertiserId),
		onSuccess: invalidate,
	});
};
