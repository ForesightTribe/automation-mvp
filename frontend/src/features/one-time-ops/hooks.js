import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useAutomationMarketplace } from "../../context/MarketplaceContext";
import { invalidateCampaignData } from "../../lib/campaignData";
import {
	getCampaigns,
	setBudgetNow,
	setActivationNow,
	refreshCampaigns,
	getCampaignTargets,
	getCatalogKeywords,
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
 *
 * Every hook acts on ONE marketplace — the navbar's choice for this page — and carries it
 * in its cache key, so switching marketplace never shows the other one's rows.
 */
const CAMPAIGNS = "ots-campaigns";

/** The active client and the page's marketplace; `ready` once both are known. */
const useScope = () => {
	const { activeClientId } = useClient();
	const { marketplace: mp } = useAutomationMarketplace();
	return { activeClientId, mp, ready: Boolean(activeClientId && mp) };
};

/** The account's campaigns, over the window the navbar has selected. */
export const useCampaigns = () => {
	const { activeClientId, mp, ready } = useScope();
	const { days } = useDateRange();
	return useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp, days],
		queryFn: () => getCampaigns(activeClientId, mp, { days }),
		enabled: ready,
		select: (page) => page.items ?? [],
	});
};

/**
 * One campaign's targets. Only fetched while its drawer is open.
 *
 * Blinkit: its keyword performance over the window. Elsewhere (Zepto): the keywords the
 * catalogue says the campaign bids on, with the live bid and floor and no performance —
 * `catalog: true` on each row tells the drawer which columns to draw. The catalogue is one
 * request for the whole account, cached, then filtered to the campaign.
 */
export const useCampaignTargets = (campaignId) => {
	const { activeClientId, mp, ready } = useScope();
	const { days } = useDateRange();
	const blinkit = mp === "blinkit";
	const perf = useQuery({
		queryKey: ["ots-targets", activeClientId, campaignId, days],
		queryFn: () => getCampaignTargets(activeClientId, campaignId, { days }),
		enabled: Boolean(ready && blinkit && campaignId),
		select: (page) => page.items ?? [],
		staleTime: 5 * 60 * 1000,
	});
	const catalog = useQuery({
		queryKey: [CAMPAIGNS, activeClientId, mp, "catalog-keywords"],
		queryFn: () => getCatalogKeywords(activeClientId, mp),
		enabled: Boolean(ready && !blinkit && campaignId),
		staleTime: 5 * 60 * 1000,
	});
	if (blinkit) return perf;
	return {
		...catalog,
		data: (catalog.data ?? [])
			.filter((k) => k.campaign_id === campaignId)
			.map((k) => ({
				...k,
				target: k.keyword,
				target_type: "keyword",
				catalog: true,
			})),
	};
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
	const { activeClientId, mp, ready } = useScope();
	const qc = useQueryClient();
	return useQuery({
		queryKey: ["ots-job", activeClientId, mp, jobId],
		queryFn: async () => {
			const job = await getJob(activeClientId, mp, jobId);
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
		enabled: Boolean(ready && jobId),
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
	const { activeClientId, mp, ready } = useScope();
	return useQuery({
		queryKey: ["ots-verdict", activeClientId, mp, campaignId],
		queryFn: () => getLastVerdict(activeClientId, mp, campaignId),
		enabled: Boolean(ready && campaignId && enabled),
		select: (page) => page.items?.[0] ?? null,
		staleTime: 0,
		gcTime: 0,
	});
};

export const useSetBudget = () => {
	const { activeClientId, mp } = useScope();
	return useMutation({
		mutationFn: ({ campaignId, budget }) =>
			setBudgetNow(activeClientId, mp, campaignId, budget),
	});
};

export const useSetActivation = () => {
	const { activeClientId, mp } = useScope();
	return useMutation({
		mutationFn: ({ campaignId, status, budget }) =>
			setActivationNow(activeClientId, mp, campaignId, status, budget),
	});
};

export const useRefreshCampaigns = () => {
	const { activeClientId, mp } = useScope();
	return useMutation({
		mutationFn: () => refreshCampaigns(activeClientId, mp),
	});
};
