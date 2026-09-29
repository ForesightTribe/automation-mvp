import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useAutomationMarketplace } from "../../context/MarketplaceContext";
import { invalidateRecentActions } from "../../lib/actions";
import {
	getCampaigns,
	setBudgetNow,
	setActivationNow,
	refreshCampaigns,
	getCampaignTargets,
	getCatalogKeywords,
} from "./api";

/**
 * One-time ops: React Query hooks.
 *
 * Everything here writes to a LIVE ad account the moment it is called, so nothing is
 * optimistic and nothing is cached as though it succeeded. A write enqueues a job on the
 * VM; its progress and its real outcome come from `lib/actions.js`, and the campaign list
 * is refreshed there when the job finishes.
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
 * A write that enqueues a job. On success it tells the operations list AT ONCE — the job row
 * exists before the request returns, and without this the list kept its old all-finished
 * state and never started polling (see `invalidateRecentActions`).
 */
const useEnqueue = (mutationFn) => {
	const { activeClientId, mp } = useScope();
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (vars) => mutationFn(activeClientId, mp, vars),
		onSuccess: () => invalidateRecentActions(qc, activeClientId),
	});
};

export const useSetBudget = () =>
	useEnqueue((clientId, mp, { campaignId, budget }) =>
		setBudgetNow(clientId, mp, campaignId, budget),
	);

export const useSetActivation = () =>
	useEnqueue((clientId, mp, { campaignId, status, budget }) =>
		setActivationNow(clientId, mp, campaignId, status, budget),
	);

export const useRefreshCampaigns = () =>
	useEnqueue((clientId, mp) => refreshCampaigns(clientId, mp));
