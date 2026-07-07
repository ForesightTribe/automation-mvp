import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { AddBidOptimizerForm } from "../ads/components/campaign-manager/AddBidOptimizerForm";
import { AddScheduleForm } from "../ads/components/campaign-manager/AddScheduleForm";
import { BidOptimizerHistory } from "../ads/components/campaign-manager/BidOptimizerHistory";
import { BidOptimizerRuleList } from "../ads/components/campaign-manager/BidOptimizerRuleList";
import { ReconnectBlinkit } from "../ads/components/campaign-manager/ReconnectBlinkit";
import { ScheduleList } from "../ads/components/campaign-manager/ScheduleList";
import { SchedulerHistory } from "../ads/components/campaign-manager/SchedulerHistory";
import { SetBudget } from "../ads/components/campaign-manager/SetBudget";
import { useRunBidOptimizer, useRunScheduler } from "../ads/campaign-manager-hooks";

export const CampaignManagerPage = () => {
    const { mutate: runBudget, isPending: budgetPending, isSuccess: budgetSuccess, data: budgetResult } = useRunScheduler();
    const { mutate: runBid, isPending: bidPending, isSuccess: bidSuccess, data: bidResult } = useRunBidOptimizer();
    const [ranBudget, setRanBudget] = useState(false);
    const [ranBid, setRanBid] = useState(false);

    return (
        <div className="flex flex-col gap-6">
            <div>
                <h1 className="font-display text-xl font-bold text-content">Campaign Manager</h1>
                <p className="text-sm text-content-muted">
                    Automated budget scheduling and bid optimization for Blinkit campaigns.
                </p>
            </div>

            {/* ── Budget Scheduler ── */}
            <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                    <h2 className="text-base font-semibold text-content">Budget Scheduler</h2>
                    <Button
                        onClick={() => { runBudget(); setRanBudget(true); }}
                        disabled={budgetPending}
                        size="sm"
                    >
                        {budgetPending ? "Starting…" : "Run Scheduler Now"}
                    </Button>
                </div>

                {budgetSuccess && ranBudget && (
                    <div className="rounded-lg border border-success/30 bg-success/10 px-4 py-2.5 text-sm text-success">
                        {budgetResult?.message ?? "Scheduler started. Check history in ~30 seconds."}
                    </div>
                )}

                <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                    <SetBudget />
                    <ScheduleList />
                </div>

                <AddScheduleForm />
                <SchedulerHistory />
            </div>

            <hr className="border-border" />

            {/* ── Bid Optimizer ── */}
            <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-base font-semibold text-content">Bid Optimizer</h2>
                        <p className="text-xs text-content-muted">
                            Automatically adjusts keyword CPM bids every 30 min to hit your target position.
                        </p>
                    </div>
                    <Button
                        onClick={() => { runBid(); setRanBid(true); }}
                        disabled={bidPending}
                        size="sm"
                    >
                        {bidPending ? "Starting…" : "Run Now"}
                    </Button>
                </div>

                {bidSuccess && ranBid && (
                    <div className="rounded-lg border border-success/30 bg-success/10 px-4 py-2.5 text-sm text-success">
                        {bidResult?.message ?? "Bid optimizer started. Check history in ~30 seconds."}
                    </div>
                )}

                <BidOptimizerRuleList />
                <AddBidOptimizerForm />
                <BidOptimizerHistory />
            </div>

            <hr className="border-border" />

            <ReconnectBlinkit />
        </div>
    );
};
