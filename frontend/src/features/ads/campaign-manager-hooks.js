import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useClient } from "../../context/ClientContext";
import {
    addBidOptimizerRule,
    addBudgetSchedule,
    deleteBidOptimizerRule,
    deleteBudgetSchedule,
    toggleBudgetSchedule,
    getBidOptimizerHistory,
    getBidOptimizerRules,
    getBudgetSchedules,
    getCampaignKeywords,
    getCampaignProducts,
    getCampaigns,
    getSchedulerHistory,
    reconnectBlinkit,
    runBidOptimizer,
    runScheduler,
    setCampaignBudget,
    toggleBidOptimizerRule,
} from "./campaign-manager-api";

export const useCampaigns = () => {
    const { activeClientId } = useClient();
    return useQuery({
        queryKey: ["cm-campaigns", activeClientId],
        queryFn: () => getCampaigns(activeClientId),
        enabled: Boolean(activeClientId),
    });
};

export const useBudgetSchedules = () => {
    const { activeClientId } = useClient();
    return useQuery({
        queryKey: ["budget-schedules", activeClientId],
        queryFn: () => getBudgetSchedules(activeClientId),
        enabled: Boolean(activeClientId),
    });
};

export const useSchedulerHistory = () => {
    const { activeClientId } = useClient();
    return useQuery({
        queryKey: ["scheduler-history", activeClientId],
        queryFn: () => getSchedulerHistory(activeClientId),
        enabled: Boolean(activeClientId),
    });
};

export const useAddBudgetSchedule = () => {
    const { activeClientId } = useClient();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => addBudgetSchedule(activeClientId, data),
        onSuccess: () =>
            qc.invalidateQueries({ queryKey: ["budget-schedules", activeClientId] }),
    });
};

export const useDeleteBudgetSchedule = () => {
    const { activeClientId } = useClient();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (campaignId) => deleteBudgetSchedule(activeClientId, campaignId),
        onSuccess: () =>
            qc.invalidateQueries({ queryKey: ["budget-schedules", activeClientId] }),
    });
};

export const useToggleBudgetSchedule = () => {
    const { activeClientId } = useClient();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (campaignId) => toggleBudgetSchedule(activeClientId, campaignId),
        onSuccess: () =>
            qc.invalidateQueries({ queryKey: ["budget-schedules", activeClientId] }),
    });
};

export const useSetCampaignBudget = () => {
    const { activeClientId } = useClient();
    return useMutation({
        mutationFn: ({ campaignId, budget }) => setCampaignBudget(activeClientId, campaignId, budget),
    });
};

export const useReconnectBlinkit = () => {
    const { activeClientId } = useClient();
    return useMutation({
        mutationFn: (magicLink) => reconnectBlinkit(activeClientId, magicLink),
    });
};

export const useCampaignProducts = (campaignId) => {
    const { activeClientId } = useClient();
    return useQuery({
        queryKey: ["campaign-products", activeClientId, campaignId],
        queryFn: () => getCampaignProducts(activeClientId, campaignId),
        enabled: Boolean(activeClientId && campaignId),
        staleTime: 10 * 60 * 1000,
    });
};

export const useCampaignKeywords = (campaignId) => {
    const { activeClientId } = useClient();
    return useQuery({
        queryKey: ["campaign-keywords", activeClientId, campaignId],
        queryFn: () => getCampaignKeywords(activeClientId, campaignId),
        enabled: Boolean(activeClientId && campaignId),
        staleTime: 5 * 60 * 1000,
    });
};

export const useBidOptimizerRules = () => {
    const { activeClientId } = useClient();
    return useQuery({
        queryKey: ["bid-optimizer-rules", activeClientId],
        queryFn: () => getBidOptimizerRules(activeClientId),
        enabled: Boolean(activeClientId),
    });
};

export const useBidOptimizerHistory = () => {
    const { activeClientId } = useClient();
    return useQuery({
        queryKey: ["bid-optimizer-history", activeClientId],
        queryFn: () => getBidOptimizerHistory(activeClientId),
        enabled: Boolean(activeClientId),
        refetchInterval: 30000,
    });
};

export const useAddBidOptimizerRule = () => {
    const { activeClientId } = useClient();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (data) => addBidOptimizerRule(activeClientId, data),
        onSuccess: () => qc.invalidateQueries({ queryKey: ["bid-optimizer-rules", activeClientId] }),
    });
};

export const useDeleteBidOptimizerRule = () => {
    const { activeClientId } = useClient();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (ruleId) => deleteBidOptimizerRule(activeClientId, ruleId),
        onSuccess: () => qc.invalidateQueries({ queryKey: ["bid-optimizer-rules", activeClientId] }),
    });
};

export const useToggleBidOptimizerRule = () => {
    const { activeClientId } = useClient();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (ruleId) => toggleBidOptimizerRule(activeClientId, ruleId),
        onSuccess: () => qc.invalidateQueries({ queryKey: ["bid-optimizer-rules", activeClientId] }),
    });
};

export const useRunBidOptimizer = () => {
    const { activeClientId } = useClient();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => runBidOptimizer(activeClientId),
        onSuccess: () => {
            setTimeout(
                () => qc.invalidateQueries({ queryKey: ["bid-optimizer-history", activeClientId] }),
                35000,
            );
        },
    });
};

export const useRunScheduler = () => {
    const { activeClientId } = useClient();
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => runScheduler(activeClientId),
        onSuccess: () => {
            setTimeout(
                () => qc.invalidateQueries({ queryKey: ["scheduler-history", activeClientId] }),
                35000,
            );
        },
    });
};
