import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { AddBidOptimizerForm } from "./components/AddBidOptimizerForm";
import { AddScheduleForm } from "./components/AddScheduleForm";
import { BidOptimizerHistory } from "./components/BidOptimizerHistory";
import { BidOptimizerRuleList } from "./components/BidOptimizerRuleList";
import { LivePositionCheck } from "./components/LivePositionCheck";
import { ScheduleList } from "./components/ScheduleList";
import { SchedulerHistory } from "./components/SchedulerHistory";
import { SetBudget } from "./components/SetBudget";

export const CampaignManagerPage = () => {
    const [openBidForm, setOpenBidForm] = useState(false);

    return (
        <div className="flex flex-col gap-8">

            {/* ── Page heading ── */}
            <div className="text-center">
                <h1 className="font-display text-2xl font-bold text-content">Campaign Manager</h1>
                <p className="text-sm text-content-muted mt-1">
                    Automated budget scheduling and bid optimization for Blinkit campaigns.
                </p>
            </div>

            {/* ── Budget Scheduler ── */}
            <div className="flex flex-col gap-4">
                <div className="flex flex-col items-center gap-1 py-3 border-y border-border bg-muted/30 rounded-lg">
                    <h2 className="text-lg font-bold text-content tracking-wide">Budget Scheduler</h2>
                    <p className="text-xs text-content-muted text-center max-w-md">
                        Automatically changes a campaign's daily budget at your scheduled times.
                    </p>
                    <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2.5 py-0.5 text-[11px] font-medium text-success">
                        ● Auto-runs every 5 min
                    </span>
                </div>

                <div className="flex items-center gap-3">
                    <div className="w-1 h-8 rounded-full bg-primary shrink-0" />
                    <div>
                        <p className="text-sm font-semibold text-content">Update Daily Budget</p>
                        <p className="text-xs text-content-muted">Manually set a campaign's daily budget right now on Blinkit.</p>
                    </div>
                </div>
                <SetBudget />

                <div className="flex items-center gap-3">
                    <div className="w-1 h-8 rounded-full bg-primary shrink-0" />
                    <div>
                        <p className="text-sm font-semibold text-content">Schedule a Budget Rule</p>
                        <p className="text-xs text-content-muted">Set time-based rules to automatically change the budget at specific hours or days.</p>
                    </div>
                </div>
                <AddScheduleForm />
                <ScheduleList />
                <SchedulerHistory />
            </div>

            <hr className="border-border" />

            {/* ── Bid Optimizer ── */}
            <div className="flex flex-col gap-4">
                <div className="flex flex-col items-center gap-1 py-3 border-y border-border bg-muted/30 rounded-lg">
                    <h2 className="text-lg font-bold text-content tracking-wide">Bid Optimizer</h2>
                    <p className="text-xs text-content-muted text-center max-w-md">
                        Automatically adjusts keyword CPM bids to reach your target position.
                    </p>
                    <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2.5 py-0.5 text-[11px] font-medium text-success">
                        ● Auto-runs on VM
                    </span>
                </div>

                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-1 h-8 rounded-full bg-primary shrink-0" />
                        <div>
                            <p className="text-sm font-semibold text-content">Add Bid Optimizer Rule</p>
                            <p className="text-xs text-content-muted">Set a keyword target position and bid range for a campaign.</p>
                        </div>
                    </div>
                    <Button
                        size="sm"
                        onClick={() => setOpenBidForm(true)}
                    >
                        + New Bid Rule
                    </Button>
                </div>

                {/* <LivePositionCheck brandName="dobra" /> */}
                <BidOptimizerRuleList />
                <AddBidOptimizerForm triggerOpen={openBidForm} onTriggerConsumed={() => setOpenBidForm(false)} />
                <BidOptimizerHistory />
            </div>

        </div>
    );
};
