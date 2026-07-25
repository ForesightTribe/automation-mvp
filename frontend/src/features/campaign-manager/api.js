import { api } from "../../lib/axios";

export const getCampaigns = (clientId) => {
    const end = new Date().toISOString().split("T")[0];
    const start = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split("T")[0];
    return api.get(`/clients/${clientId}/ads/campaigns`, { params: { limit: 500, start, end, recent_only: true } });
};

export const getBudgetSchedules = (clientId) =>
    api.get(`/clients/${clientId}/ads/budget-schedules`);

export const addBudgetSchedule = (clientId, data) =>
    api.post(`/clients/${clientId}/ads/budget-schedules`, data);

export const deleteBudgetSchedule = (clientId, campaignId) =>
    api.delete(`/clients/${clientId}/ads/budget-schedules/${campaignId}`);

export const toggleBudgetSchedule = (clientId, campaignId) =>
    api.patch(`/clients/${clientId}/ads/budget-schedules/${campaignId}/toggle`);

export const getSchedulerHistory = (clientId) =>
    api.get(`/clients/${clientId}/ads/budget-schedules/history`);

export const runScheduler = (clientId) =>
    api.post(`/clients/${clientId}/ads/budget-schedules/run`);

export const reconnectBlinkit = (clientId, magicLink) =>
    api.post(`/clients/${clientId}/ads/reconnect-blinkit`, { magic_link: magicLink });

export const setCampaignBudget = (clientId, campaignId, budget) =>
    api.post(`/clients/${clientId}/ads/campaigns/${campaignId}/set-budget`, { budget });

export const getLivePositions = (clientId, keyword, lat, lon) =>
    api.get(`/clients/${clientId}/ads/live-position`, { params: { keyword, lat, lon } });

export const getLiveBudget = (clientId, campaignId) =>
    api.get(`/clients/${clientId}/ads/campaigns/${campaignId}/live-budget`);

export const getCampaignProducts = (clientId, campaignId) =>
    api.get(`/clients/${clientId}/ads/campaigns/${campaignId}/products`);

export const getCampaignKeywords = (clientId, campaignId) =>
    api.get(`/clients/${clientId}/ads/campaigns/${campaignId}/keywords`);

export const getBidOptimizerRules = (clientId) =>
    api.get(`/clients/${clientId}/ads/bid-optimizer/rules`);

export const addBidOptimizerRule = (clientId, data) =>
    api.post(`/clients/${clientId}/ads/bid-optimizer/rules`, data);

export const deleteBidOptimizerRule = (clientId, ruleId) =>
    api.delete(`/clients/${clientId}/ads/bid-optimizer/rules/${ruleId}`);

export const toggleBidOptimizerRule = (clientId, ruleId) =>
    api.patch(`/clients/${clientId}/ads/bid-optimizer/rules/${ruleId}/toggle`);

export const getBidOptimizerHistory = (clientId) =>
    api.get(`/clients/${clientId}/ads/bid-optimizer/history`);

export const runBidOptimizer = (clientId) =>
    api.post(`/clients/${clientId}/ads/bid-optimizer/run`);

