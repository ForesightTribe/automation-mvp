import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { useAddBudgetSchedule, useCampaigns } from "../hooks";
import { CampaignSelector } from "./CampaignSelector";

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const SLOTS = [
    { key: "morning", label: "Morning (6–12)" },
    { key: "afternoon", label: "Afternoon (12–18)" },
    { key: "evening", label: "Evening (18–22)" },
    { key: "night", label: "Night (22–6)" },
];

const emptyRule = () => ({
    type: "recurring",
    days: [],
    time_slots: [],
    budget: "",
    date: "",
    start_date: "",
    end_date: "",
    start_time: "",
    end_time: "",
});

const Toggle = ({ checked, onChange, label }) => (
    <label className="flex cursor-pointer items-center gap-1.5 text-xs">
        <input
            type="checkbox"
            checked={checked}
            onChange={onChange}
            className="h-3.5 w-3.5 rounded"
        />
        <span className="capitalize text-content-muted">{label}</span>
    </label>
);

export const AddScheduleForm = () => {
    const { data: campaignsPage } = useCampaigns();
    const campaigns = campaignsPage?.items ?? [];

    const [open, setOpen] = useState(false);
    const [scheduleName, setScheduleName] = useState("");
    const [campaignId, setCampaignId] = useState("");
    const [campaignName, setCampaignName] = useState("");
    const [defaultBudget, setDefaultBudget] = useState("");

    const currentBudget = campaignId
        ? campaigns.find((c) => String(c.campaign_id) === String(campaignId))?.daily_budget ?? null
        : null;
    const [rules, setRules] = useState([]);
    const [rule, setRule] = useState(emptyRule());
    const [ruleOpen, setRuleOpen] = useState(false);

    const { mutate: addSchedule, isPending } = useAddBudgetSchedule();

    const toggleDay = (day) =>
        setRule((r) => ({
            ...r,
            days: r.days.includes(day) ? r.days.filter((d) => d !== day) : [...r.days, day],
        }));

    const toggleSlot = (slot) =>
        setRule((r) => ({
            ...r,
            time_slots: r.time_slots.includes(slot)
                ? r.time_slots.filter((s) => s !== slot)
                : [...r.time_slots, slot],
        }));

    const confirmRule = () => {
        if (!rule.budget) return;
        if (rule.type === "once" && !rule.date) return;
        // Need at least one constraint — time slot, time range, specific days, or date range
        const hasAnyConstraint =
            rule.time_slots.length > 0 || rule.start_time || rule.end_time ||
            rule.days.length > 0 || rule.start_date || rule.end_date;
        if (rule.type === "recurring" && !hasAnyConstraint) return;
        setRules((rs) => [
            ...rs,
            {
                ...rule,
                budget: parseFloat(rule.budget),
                start_date: rule.start_date || null,
                end_date: rule.end_date || null,
                start_time: rule.start_time || null,
                end_time: rule.end_time || null,
            },
        ]);
        setRule(emptyRule());
        setRuleOpen(false);
    };

    const reset = () => {
        setScheduleName("");
        setCampaignId("");
        setCampaignName("");
        setDefaultBudget("");
        setRules([]);
        setRule(emptyRule());
        setRuleOpen(false);
        setOpen(false);
    };

    const submit = () => {
        if (!campaignId || !defaultBudget) return;
        addSchedule(
            {
                campaign_id: parseInt(campaignId),
                campaign_name: campaignName || `Campaign ${campaignId}`,
                name: scheduleName.trim() || null,
                default_budget: parseFloat(defaultBudget),
                rules,
            },
            { onSuccess: reset },
        );
    };

    return (
        <Card
            title="Add New Schedule"
            actions={
                !open && (
                    <Button size="sm" onClick={() => setOpen(true)}>
                        + Add
                    </Button>
                )
            }
        >
            {!open ? (
                <p className="text-sm text-content-muted">
                    Set automatic budget rules for a campaign.
                </p>
            ) : (
                <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">Schedule Name</label>
                        <input
                            type="text"
                            value={scheduleName}
                            onChange={(e) => setScheduleName(e.target.value)}
                            placeholder="e.g. Soda Weekend Boost"
                            className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                        />
                    </div>
                    <CampaignSelector
                        value={campaignId}
                        onChange={(id, name) => { setCampaignId(id); setCampaignName(name); }}
                    />
                    {currentBudget != null && (
                        <div className="rounded-md bg-primary/10 px-3 py-2 text-xs text-primary">
                            Current budget: <span className="font-semibold">₹{currentBudget.toLocaleString()}</span> / day
                        </div>
                    )}

                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">
                            Default Budget ₹ (applied outside scheduled slots)
                        </label>
                        <input
                            type="number"
                            value={defaultBudget}
                            onChange={(e) => setDefaultBudget(e.target.value)}
                            placeholder={currentBudget != null ? `Current: ₹${currentBudget.toLocaleString()}` : "e.g. 500"}
                            className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                        />
                    </div>

                    {/* Existing rules */}
                    {rules.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                            <p className="text-xs font-medium text-content-muted">Rules added:</p>
                            {rules.map((r, i) => (
                                <div
                                    key={i}
                                    className="flex items-center justify-between rounded bg-muted px-3 py-1.5 text-xs"
                                >
                                    <span className="text-content-muted">
                                        {r.type === "once"
                                            ? `📅 ${r.date}`
                                            : `🔁 ${r.days.length ? r.days.join(", ") : "every day"}`}
                                        {(r.start_date || r.end_date) && (
                                            <span> ({r.start_date || "…"}–{r.end_date || "…"})</span>
                                        )}
                                        {" · "}
                                        {(r.start_time || r.end_time)
                                            ? `${r.start_time || "00:00"}–${r.end_time || "23:59"}`
                                            : r.time_slots.join(", ")}
                                        {" → "}
                                        <span className="font-semibold text-content">
                                            ₹{r.budget.toLocaleString()}
                                        </span>
                                    </span>
                                    <button
                                        onClick={() => setRules((rs) => rs.filter((_, j) => j !== i))}
                                        className="ml-2 text-danger hover:opacity-75"
                                    >
                                        ✕
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Add rule section */}
                    {!ruleOpen ? (
                        <Button variant="secondary" size="sm" onClick={() => setRuleOpen(true)}>
                            + Add Rule
                        </Button>
                    ) : (
                        <div className="flex flex-col gap-3 rounded-lg border border-border p-3">
                            <p className="text-xs font-semibold text-content">New Rule</p>

                            {/* Type toggle */}
                            <div className="flex gap-3">
                                {["recurring", "once"].map((t) => (
                                    <label key={t} className="flex cursor-pointer items-center gap-1.5 text-xs">
                                        <input
                                            type="radio"
                                            checked={rule.type === t}
                                            onChange={() => setRule((r) => ({ ...r, type: t, days: [], date: "" }))}
                                        />
                                        <span className="capitalize text-content">
                                            {t === "recurring" ? "Recurring (weekly)" : "One-time (specific date)"}
                                        </span>
                                    </label>
                                ))}
                            </div>

                            {/* Days or date */}
                            {rule.type === "recurring" ? (
                                <div>
                                    <p className="mb-1.5 text-xs text-content-muted">Days</p>
                                    <div className="flex flex-wrap gap-2">
                                        {DAYS.map((d) => (
                                            <Toggle
                                                key={d}
                                                label={d.slice(0, 3)}
                                                checked={rule.days.includes(d)}
                                                onChange={() => toggleDay(d)}
                                            />
                                        ))}
                                    </div>
                                </div>
                            ) : (
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs text-content-muted">Date</label>
                                    <input
                                        type="date"
                                        value={rule.date}
                                        onChange={(e) => setRule((r) => ({ ...r, date: e.target.value }))}
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                            )}

                            {/* Time slots */}
                            <div>
                                <p className="mb-1.5 text-xs text-content-muted">Time Slots</p>
                                <div className="flex flex-wrap gap-3">
                                    {SLOTS.map((s) => (
                                        <Toggle
                                            key={s.key}
                                            label={s.label}
                                            checked={rule.time_slots.includes(s.key)}
                                            onChange={() => toggleSlot(s.key)}
                                        />
                                    ))}
                                </div>
                            </div>

                            {/* Budget */}
                            <div className="flex flex-col gap-1">
                                <label className="text-xs text-content-muted">
                                    Budget ₹ for this slot
                                </label>
                                <input
                                    type="number"
                                    value={rule.budget}
                                    onChange={(e) => setRule((r) => ({ ...r, budget: e.target.value }))}
                                    placeholder="e.g. 2000"
                                    className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                />
                            </div>

                            {/* Date range — only for recurring rules */}
                            {rule.type === "recurring" && (
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="flex flex-col gap-1">
                                        <label className="text-xs text-content-muted">Start Date (optional)</label>
                                        <input
                                            type="date"
                                            value={rule.start_date}
                                            onChange={(e) => setRule((r) => ({ ...r, start_date: e.target.value }))}
                                            className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                        />
                                    </div>
                                    <div className="flex flex-col gap-1">
                                        <label className="text-xs text-content-muted">End Date (optional)</label>
                                        <input
                                            type="date"
                                            value={rule.end_date}
                                            onChange={(e) => setRule((r) => ({ ...r, end_date: e.target.value }))}
                                            className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                        />
                                    </div>
                                </div>
                            )}

                            {/* Time range */}
                            <div className="grid grid-cols-2 gap-3">
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs text-content-muted">Start Time IST (optional)</label>
                                    <input
                                        type="time"
                                        value={rule.start_time}
                                        onChange={(e) => setRule((r) => ({ ...r, start_time: e.target.value }))}
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs text-content-muted">End Time IST (optional)</label>
                                    <input
                                        type="time"
                                        value={rule.end_time}
                                        onChange={(e) => setRule((r) => ({ ...r, end_time: e.target.value }))}
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                            </div>

                            <div className="flex gap-2">
                                <Button size="sm" onClick={confirmRule}>
                                    Confirm Rule
                                </Button>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => { setRule(emptyRule()); setRuleOpen(false); }}
                                >
                                    Cancel
                                </Button>
                            </div>
                        </div>
                    )}

                    {/* Form actions */}
                    <div className="flex gap-2 pt-1">
                        <Button onClick={submit} disabled={isPending || !campaignId || !defaultBudget}>
                            {isPending ? "Saving…" : "Save Schedule"}
                        </Button>
                        <Button variant="secondary" onClick={reset}>
                            Cancel
                        </Button>
                    </div>
                </div>
            )}
        </Card>
    );
};



