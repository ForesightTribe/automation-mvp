import { useState } from "react";
import { Button } from "../../../../components/ui/Button";
import { Card } from "../../../../components/ui/Card";
import { useCampaigns, useSetCampaignBudget } from "../../hooks";
import { CampaignSelector } from "./CampaignSelector";

export const SetBudget = () => {
    const [campaignId, setCampaignId] = useState("");
    const [budget, setBudget] = useState("");

    const { data: campaignsPage } = useCampaigns();
    const campaigns = campaignsPage?.items ?? [];

    const { mutate, isPending, isSuccess, isError, error, data, reset } = useSetCampaignBudget();

    const selectedCampaign = campaigns.find((c) => String(c.campaign_id) === String(campaignId));
    const currentBudget = selectedCampaign?.daily_budget;

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

                {campaignId && currentBudget != null && (
                    <p className="text-xs text-content-muted">
                        Current daily budget: <span className="font-semibold text-content">₹{currentBudget.toLocaleString("en-IN")}</span>
                    </p>
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
