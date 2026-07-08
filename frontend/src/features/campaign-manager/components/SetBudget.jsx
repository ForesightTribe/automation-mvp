import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { useCampaigns, useLiveBudget, useSetCampaignBudget } from "../hooks";
import { CampaignSelector } from "./CampaignSelector";

export const SetBudget = () => {
    const [campaignId, setCampaignId] = useState("");
    const [budget, setBudget] = useState("");

    const { data: campaignsPage } = useCampaigns();
    const campaigns = campaignsPage?.items ?? [];

    const { mutate, isPending, isSuccess, isError, error, data, reset } = useSetCampaignBudget();
    const { mutate: fetchLiveBudget, isPending: fetchingBudget, data: liveData } = useLiveBudget();

    const selectedCampaign = campaigns.find((c) => String(c.campaign_id) === String(campaignId));
    const liveBudget = liveData?.data?.campaign_budget;
    const currentBudget = liveBudget ?? selectedCampaign?.daily_budget;

    const handleSubmit = () => {
        if (!campaignId || !budget) return;
        mutate(
            { campaignId: parseInt(campaignId), budget: parseFloat(budget) },
            { onSuccess: () => { setBudget(""); } },
        );
    };

    return (
        <Card title="Update Daily Budget">
            <div className="flex flex-col gap-3">
                <CampaignSelector
                    value={campaignId}
                    onChange={(id) => { setCampaignId(id); reset(); }}
                />

                {campaignId && (
                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">Current Daily Budget (Blinkit)</label>
                        <div className="flex items-center gap-2">
                            <div className="flex-1 rounded-md border border-border bg-surface px-3 py-1.5 text-sm">
                                {fetchingBudget
                                    ? <span className="italic text-content-muted">Fetching from Blinkit…</span>
                                    : currentBudget != null
                                        ? <span className="font-semibold text-content">₹{currentBudget.toLocaleString("en-IN")}</span>
                                        : <span className="italic text-content-muted">Not synced yet</span>
                                }
                            </div>
                            <button
                                type="button"
                                onClick={() => fetchLiveBudget(parseInt(campaignId))}
                                disabled={fetchingBudget}
                                className="shrink-0 rounded-md border border-border px-2.5 py-1.5 text-xs text-content-muted hover:border-primary hover:text-primary disabled:opacity-50"
                            >
                                {fetchingBudget ? "…" : "Fetch"}
                            </button>
                        </div>
                        {fetchingBudget && (
                            <p className="text-xs text-content-muted">Connecting to Blinkit… (~20s)</p>
                        )}
                    </div>
                )}

                <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-muted">New Daily Budget ₹</label>
                    <input
                        type="number"
                        value={budget}
                        onChange={(e) => { setBudget(e.target.value); reset(); }}
                        placeholder="e.g. 2000"
                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                    />
                </div>

                {isSuccess && (
                    <p className="text-xs text-success">{data?.message ?? "Budget updated."}</p>
                )}
                {isError && (
                    <p className="text-xs text-danger">
                        {error?.response?.data?.detail ?? "Update failed. Check if session is active."}
                    </p>
                )}

                <Button
                    onClick={handleSubmit}
                    disabled={isPending || !campaignId || !budget}
                    className="w-fit"
                >
                    {isPending ? "Updating… (~20s)" : "Apply Budget"}
                </Button>

                {isPending && (
                    <p className="text-xs text-content-muted">
                        Connecting to Blinkit and applying budget… this takes ~20 seconds.
                    </p>
                )}
            </div>
        </Card>
    );
};



