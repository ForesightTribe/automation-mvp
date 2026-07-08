import {
	keepPreviousData,
	useMutation,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import {
	createRule,
	deleteRule,
	evaluateNow,
	getActions,
	getRules,
	resolveAction,
	updateRule,
} from "./api";

/**
 * Data hooks for the Ad Automation page. Rules and actions are both
 * client-scoped, so every key includes `activeClientId`. Mutations invalidate
 * the relevant query so the page reflects the change without a manual refetch.
 */
export const useRules = () => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["ad-automation-rules", activeClientId],
		queryFn: () => getRules(activeClientId),
		enabled: Boolean(activeClientId),
	});
};

export const useCreateRule = () => {
	const { activeClientId } = useClient();
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (payload) => createRule(activeClientId, payload),
		onSuccess: () =>
			queryClient.invalidateQueries({
				queryKey: ["ad-automation-rules", activeClientId],
			}),
	});
};

export const useUpdateRule = () => {
	const { activeClientId } = useClient();
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ ruleId, payload }) =>
			updateRule(activeClientId, ruleId, payload),
		onSuccess: () =>
			queryClient.invalidateQueries({
				queryKey: ["ad-automation-rules", activeClientId],
			}),
	});
};

export const useDeleteRule = () => {
	const { activeClientId } = useClient();
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (ruleId) => deleteRule(activeClientId, ruleId),
		onSuccess: () =>
			queryClient.invalidateQueries({
				queryKey: ["ad-automation-rules", activeClientId],
			}),
	});
};

/** Runs every active rule now (instead of waiting on a cron — Phase 1 has no
 * scheduler wired up) and refreshes the actions queue with whatever it found. */
export const useEvaluateNow = () => {
	const { activeClientId } = useClient();
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: () => evaluateNow(activeClientId),
		onSuccess: () =>
			queryClient.invalidateQueries({
				queryKey: ["ad-automation-actions", activeClientId],
			}),
	});
};

export const useActions = ({ status, page = 1, limit = 20 } = {}) => {
	const { activeClientId } = useClient();
	return useQuery({
		queryKey: ["ad-automation-actions", activeClientId, status, page, limit],
		queryFn: () => getActions(activeClientId, { status, page, limit }),
		enabled: Boolean(activeClientId),
		placeholderData: keepPreviousData,
	});
};

export const useResolveAction = () => {
	const { activeClientId } = useClient();
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ actionId, status }) =>
			resolveAction(activeClientId, actionId, status),
		onSuccess: () =>
			queryClient.invalidateQueries({
				queryKey: ["ad-automation-actions", activeClientId],
			}),
	});
};
