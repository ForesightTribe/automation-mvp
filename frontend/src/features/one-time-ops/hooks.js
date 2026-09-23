import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { invalidateRecentActions } from "../../lib/actions";
import {
	getCampaigns,
	setBudgetNow,
	setActivationNow,
	refreshCampaigns,
	getCampaignTargets,
} from "./api";

/**
 * One-time ops: React Query hooks.
 *
 * Everything here writes to a LIVE ad account the moment it is called, so nothing is
 * optimistic and nothing is cached as though it succeeded. A write enqueues a job on the
 * VM; its progress and its real outcome come from `lib/actions.js`, and the campaign list
 * is refreshed there when the job finishes.
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
 * A write that enqueues a job. On success it tells the operations list AT ONCE — the job row
 * exists before the request returns, and without this the list kept its old all-finished
 * state and never started polling (see `invalidateRecentActions`).
 */
const useEnqueue = (mutationFn) => {
	const { activeClientId } = useClient();
	const qc = useQueryClient();
	return useMutation({
		mutationFn: (vars) => mutationFn(activeClientId, vars),
		onSuccess: () => invalidateRecentActions(qc, activeClientId),
	});
};

export const useSetBudget = () =>
	useEnqueue((clientId, { campaignId, budget }) =>
		setBudgetNow(clientId, campaignId, budget),
	);

export const useSetActivation = () =>
	useEnqueue((clientId, { campaignId, status, budget }) =>
		setActivationNow(clientId, campaignId, status, budget),
	);

export const useRefreshCampaigns = () =>
	useEnqueue((clientId) => refreshCampaigns(clientId));
