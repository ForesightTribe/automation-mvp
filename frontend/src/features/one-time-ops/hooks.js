import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { invalidateCampaignData } from "../../lib/campaignData";
import {
	getCampaigns,
	setBudgetNow,
	setActivationNow,
	refreshCampaigns,
	getCampaignTargets,
	getLastVerdict,
	getJob,
} from "./api";

/**
 * One-time ops: React Query hooks.
 *
 * Everything here writes to a LIVE ad account the moment it is called, so nothing is
 * optimistic and nothing is cached as though it succeeded. A write enqueues a job on the
 * VM and returns its id; the truth arrives when that job finishes and the catalogue is
 * re-read.
 */
const CAMPAIGNS = "ots-campaigns";

/** The account's campaigns, over the window the navbar has selected. */
export const useCampaigns = () => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, days],
		queryFn: () => getCampaigns(activeClientId, { days }),
		enabled: Boolean(activeClientId),
		select: (page) => page.items ?? [],
	});
};

/** One campaign's targets. Only fetched while its drawer is open. */
export const useCampaignTargets = (campaignId) => {
	const { activeClientId } = useClient();
	const { days } = useDateRange();
	return useQuery({
		queryKey: ["ots-targets", activeClientId, campaignId, days],
		queryFn: () => getCampaignTargets(activeClientId, campaignId, { days }),
		enabled: Boolean(activeClientId && campaignId),
		select: (page) => page.items ?? [],
		staleTime: 5 * 60 * 1000,
	});
};

/**
 * Poll one enqueued job until it settles.
 *
 * ⚠️ On success the campaign list is invalidated, not patched. What the account now says
 * is the only reliable answer: the VM applies its own guardrails (terminal states, budget
 * bounds, rate limits) against a fresh read, so a job can succeed having done something
 * other than exactly what was asked.
 */
export const useJob = (jobId, { onSettled } = {}) => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	return useQuery({
		queryKey: ["ots-job", activeClientId, jobId],
		queryFn: async () => {
			const job = await getJob(activeClientId, jobId);
			if (job.status === "success" || job.status === "failed") {
				// Every screen's campaign data, not just this page's. A budget written
				// here also changes what Ads Insights divides by — and that page's
				// utilisation is a RATIO, so a stale denominator reads as a confident
				// wrong percentage rather than as stale. See lib/campaignData.js.
				invalidateCampaignData(qc, activeClientId);
				onSettled?.(job);
			}
			return job;
		},
		enabled: Boolean(activeClientId && jobId),
		refetchInterval: (query) => {
			const s = query.state.data?.status;
			return s === "success" || s === "failed" ? false : 1500;
		},
	});
};

/**
 * What the engine actually did, read once a job has settled.
 *
 * Polling it before then would report the PREVIOUS action on that campaign, which is
 * worse than saying nothing: it would confirm a change that has not happened yet.
 */
export const useLastVerdict = (campaignId, enabled) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["ots-verdict", activeClientId, campaignId],
		queryFn: () => getLastVerdict(activeClientId, campaignId),
		enabled: Boolean(activeClientId && campaignId && enabled),
		select: (page) => page.items?.[0] ?? null,
		staleTime: 0,
		gcTime: 0,
	});
};

export const useSetBudget = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: ({ campaignId, budget }) =>
			setBudgetNow(activeClientId, campaignId, budget),
	});
};

export const useSetActivation = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: ({ campaignId, status, budget }) =>
			setActivationNow(activeClientId, campaignId, status, budget),
	});
};

export const useRefreshCampaigns = () => {
	const { activeClientId } = useClient();
	return useMutation({
		mutationFn: () => refreshCampaigns(activeClientId),
	});
};
