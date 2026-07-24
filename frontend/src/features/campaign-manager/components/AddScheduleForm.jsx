import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { useAddBudgetSchedule, useCampaigns } from "../hooks";
import { CampaignSelector } from "./CampaignSelector";

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

const windowMinutes = (start, end) => {
    if (!start || !end) return null;
    const [sh, sm] = start.split(":").map(Number);
    const [eh, em] = end.split(":").map(Number);
    const diff = (eh * 60 + em) - (sh * 60 + sm);
    // Handle overnight windows (e.g. 22:00 → 02:00)
    return diff <= 0 ? diff + 24 * 60 : diff;
};

const emptyTimeRange = () => ({ start_time: "", end_time: "" });

const emptyRule = () => ({
    type: "recurring",
    days: [],
    budget: "",
    date: "",
    start_date: "",
    end_date: "",
    time_ranges: [emptyTimeRange()],
});

const Toggle = ({ checked, onChange, label }) => (
    <label className="flex cursor-pointer items-center gap-1.5 text-xs">
        <input type="checkbox" checked={checked} onChange={onChange} className="h-3.5 w-3.5 rounded" />
        <span className="capitalize text-content-muted">{label}</span>
    </label>
);

const inputCls = "rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary w-full";

export const AddScheduleForm = () => {
    const { data: campaignsPage } = useCampaigns();
    const campaigns = campaignsPage?.items ?? [];

    const [open, setOpen] = useState(false);
    const [scheduleName, setScheduleName] = useState("");
    const [campaignId, setCampaignId] = useState("");
    const [campaignName, setCampaignName] = useState("");
    const [defaultBudget, setDefaultBudget] = useState("");

    const [rules, setRules] = useState([]);
    const [rule, setRule] = useState(emptyRule());
    const [ruleOpen, setRuleOpen] = useState(false);
    const [ruleError, setRuleError] = useState("");

    const { mutate: addSchedule, isPending } = useAddBudgetSchedule();

    const toggleDay = (day) =>
        setRule((r) => ({
            ...r,
            days: r.days.includes(day) ? r.days.filter((d) => d !== day) : [...r.days, day],
        }));

    // Time range helpers
    const updateTimeRange = (idx, field, value) =>
        setRule((r) => {
            const tr = [...r.time_ranges];
            tr[idx] = { ...tr[idx], [field]: value };
            return { ...r, time_ranges: tr };
        });
    const addTimeRange = () =>
        setRule((r) => ({ ...r, time_ranges: [...r.time_ranges, emptyTimeRange()] }));
    const removeTimeRange = (idx) =>
        setRule((r) => ({ ...r, time_ranges: r.time_ranges.filter((_, i) => i !== idx) }));

    const confirmRule = () => {
        setRuleError("");
        if (!rule.budget) { setRuleError("Please enter a budget amount."); return; }

        if (rule.type === "once") {
            if (!rule.date) { setRuleError("Please select a date for this one-time rule."); return; }
            for (let i = 0; i < rule.time_ranges.length; i++) {
                if (!rule.time_ranges[i].start_time) {
                    setRuleError(`Time slot ${i + 1}: Start time is required.`); return;
                }
            }
            // One-time: one rule per time range
            const newRules = rule.time_ranges.map((tr) => ({
                type: "once",
                days: [],
                time_slots: [],
                budget: parseFloat(rule.budget),
                date: rule.date,
                start_date: null,
                end_date: null,
                start_time: tr.start_time,
                end_time: tr.end_time || null,
            }));
            setRules((rs) => [...rs, ...newRules]);
        } else {
            if (!rule.days.length) { setRuleError("Please select at least one day."); return; }
            if (!rule.start_date) { setRuleError("Start date is required."); return; }
            for (let i = 0; i < rule.time_ranges.length; i++) {
                if (!rule.time_ranges[i].start_time) {
                    setRuleError(`Time slot ${i + 1}: Start time is required.`); return;
                }
                if (!rule.time_ranges[i].end_time) {
                    setRuleError(`Time slot ${i + 1}: End time is required.`); return;
                }
            }
            // Recurring: one rule per time range, all sharing the same date range
            const newRules = rule.time_ranges.map((tr) => ({
                type: "recurring",
                days: rule.days,
                time_slots: [],
                budget: parseFloat(rule.budget),
                date: null,
                start_date: rule.start_date,
                end_date: rule.end_date || null,
                start_time: tr.start_time,
                end_time: tr.end_time || null,
            }));
            setRules((rs) => [...rs, ...newRules]);
        }

        setRule(emptyRule());
        setRuleError("");
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
            actions={!open && <Button size="sm" onClick={() => setOpen(true)}>+ New Schedule</Button>}
        >
            {!open ? (
                <p className="text-sm text-content-muted">Set automatic budget rules for a campaign.</p>
            ) : (
                <div className="flex flex-col gap-4">
                    {/* Schedule name */}
                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">Schedule Name</label>
                        <input
                            type="text"
                            value={scheduleName}
                            onChange={(e) => setScheduleName(e.target.value)}
                            placeholder="e.g. Soda Weekend Boost"
                            className={inputCls}
                        />
                    </div>

                    <CampaignSelector
                        value={campaignId}
                        onChange={(id, name) => { setCampaignId(id); setCampaignName(name); }}
                    />


                    {/* Default budget */}
                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">
                            Default Budget ₹ <span className="text-content-muted font-normal">(applied outside scheduled slots)</span>
                        </label>
                        <input
                            type="number"
                            value={defaultBudget}
                            onChange={(e) => setDefaultBudget(e.target.value)}
                            placeholder="e.g. 500"
                            className={inputCls}
                        />
                    </div>

                    {/* Rules added */}
                    {rules.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                            <p className="text-xs font-medium text-content-muted">Rules added ({rules.length}):</p>
                            {rules.map((r, i) => (
                                <div key={i} className="flex items-center justify-between rounded bg-muted px-3 py-1.5 text-xs">
                                    <span className="text-content-muted">
                                        {r.type === "once"
                                            ? `📅 ${r.date}`
                                            : `🔁 ${r.days.length ? r.days.map(d => d.slice(0,3)).join(", ") : "every day"}`}
                                        {r.start_date && <span> · {r.start_date}{r.end_date ? ` → ${r.end_date}` : " onwards"}</span>}
                                        {" · "}
                                        <span className="font-medium text-content">{r.start_time}{r.end_time ? `–${r.end_time}` : "+"}</span>
                                        {" → "}
                                        <span className="font-semibold text-content">₹{r.budget.toLocaleString()}</span>
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

                    {/* Add rule */}
                    {!ruleOpen ? (
                        <Button variant="secondary" size="sm" onClick={() => setRuleOpen(true)}>
                            + Add Rule
                        </Button>
                    ) : (
                        <div className="flex flex-col gap-4 rounded-lg border border-border p-4">
                            <div className="flex items-center justify-between">
                                <p className="text-xs font-semibold text-content">New Rule</p>
                                <span className="text-[10px] text-content-muted italic">Scheduler checks every 5 min (IST)</span>
                            </div>

                            {/* Rule type */}
                            <div className="flex gap-4">
                                {[
                                    { value: "recurring", label: "Recurring (weekly)" },
                                    { value: "once", label: "One-time (specific date)" },
                                ].map(({ value, label }) => (
                                    <label key={value} className="flex cursor-pointer items-center gap-1.5 text-xs">
                                        <input
                                            type="radio"
                                            checked={rule.type === value}
                                            onChange={() => setRule((r) => ({ ...emptyRule(), type: value }))}
                                        />
                                        <span className="text-content">{label}</span>
                                    </label>
                                ))}
                            </div>

                            {/* One-time: single date */}
                            {rule.type === "once" && (
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-content-muted">
                                        Date <span className="text-danger">*</span>
                                    </label>
                                    <input
                                        type="date"
                                        value={rule.date}
                                        onChange={(e) => setRule((r) => ({ ...r, date: e.target.value }))}
                                        className={inputCls}
                                    />
                                </div>
                            )}

                            {/* Recurring: single date range */}
                            {rule.type === "recurring" && (
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="flex flex-col gap-1">
                                        <label className="text-xs text-content-muted">
                                            Start Date <span className="text-danger">*</span>
                                        </label>
                                        <input
                                            type="date"
                                            value={rule.start_date}
                                            onChange={(e) => setRule((r) => ({ ...r, start_date: e.target.value }))}
                                            className={inputCls}
                                        />
                                    </div>
                                    <div className="flex flex-col gap-1">
                                        <label className="text-xs text-content-muted">
                                            End Date <span className="text-content-muted">(optional)</span>
                                        </label>
                                        <input
                                            type="date"
                                            value={rule.end_date}
                                            onChange={(e) => setRule((r) => ({ ...r, end_date: e.target.value }))}
                                            className={inputCls}
                                        />
                                    </div>
                                </div>
                            )}

                            {/* Recurring: day chooser */}
                            {rule.type === "recurring" && (
                                <div className="flex flex-col gap-1.5">
                                    <p className="text-xs font-medium text-content-muted">
                                        Days <span className="text-danger">*</span>
                                    </p>
                                    <div className="flex flex-wrap gap-2">
                                        <Toggle
                                            label="All"
                                            checked={rule.days.length === DAYS.length}
                                            onChange={() =>
                                                setRule((r) => ({
                                                    ...r,
                                                    days: r.days.length === DAYS.length ? [] : [...DAYS],
                                                }))
                                            }
                                        />
                                        <span className="text-content-muted">|</span>
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
                            )}

                            {/* Time slots */}
                            <div className="flex flex-col gap-2">
                                <p className="text-xs font-medium text-content-muted">
                                    Time Slots <span className="text-danger">*</span>
                                    <span className="ml-1 font-normal">(both start and end time required)</span>
                                </p>
                                {rule.time_ranges.map((tr, idx) => {
                                    const mins = windowMinutes(tr.start_time, tr.end_time);
                                    const tooShort = mins !== null && mins < 6;
                                    return (
                                        <div key={idx} className="flex flex-col gap-1">
                                            <div className="flex items-end gap-2">
                                                <div className="flex flex-1 flex-col gap-1">
                                                    <label className="text-[10px] text-content-muted">Start Time <span className="text-danger">*</span></label>
                                                    <input
                                                        type="time"
                                                        value={tr.start_time}
                                                        onChange={(e) => updateTimeRange(idx, "start_time", e.target.value)}
                                                        className={inputCls}
                                                    />
                                                </div>
                                                <div className="flex flex-1 flex-col gap-1">
                                                    <label className="text-[10px] text-content-muted">End Time <span className="text-danger">*</span></label>
                                                    <input
                                                        type="time"
                                                        value={tr.end_time}
                                                        onChange={(e) => updateTimeRange(idx, "end_time", e.target.value)}
                                                        className={inputCls}
                                                    />
                                                </div>
                                                {rule.time_ranges.length > 1 && (
                                                    <button
                                                        onClick={() => removeTimeRange(idx)}
                                                        className="mb-1.5 text-sm text-danger hover:opacity-75"
                                                    >
                                                        ✕
                                                    </button>
                                                )}
                                            </div>
                                            {tooShort && (
                                                <p className="text-[11px] text-warning flex items-center gap-1">
                                                    ⚠ Window is only {mins} min — the scheduler runs every 5 min, so keep windows at least 6 min to be safe.
                                                </p>
                                            )}
                                        </div>
                                    );
                                })}
                                {rule.time_ranges[rule.time_ranges.length - 1]?.start_time && (
                                    <button
                                        onClick={addTimeRange}
                                        className="self-start text-xs text-primary hover:underline"
                                    >
                                        + Add another time slot
                                    </button>
                                )}
                            </div>

                            {/* Budget */}
                            <div className="flex flex-col gap-1">
                                <label className="text-xs font-medium text-content-muted">
                                    Budget ₹ <span className="text-danger">*</span>
                                    <span className="ml-1 font-normal">(applied during these time slots)</span>
                                </label>
                                <input
                                    type="number"
                                    value={rule.budget}
                                    onChange={(e) => setRule((r) => ({ ...r, budget: e.target.value }))}
                                    placeholder="e.g. 2000"
                                    className={inputCls}
                                />
                            </div>

                            {ruleError && <p className="text-xs text-danger">{ruleError}</p>}

                            <div className="flex gap-2">
                                <Button size="sm" onClick={confirmRule}>Add Time Slot</Button>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => { setRule(emptyRule()); setRuleError(""); setRuleOpen(false); }}
                                >
                                    Cancel
                                </Button>
                            </div>
                        </div>
                    )}

                    {/* Form actions */}
                    <div className="flex gap-2 pt-1">
                        <Button onClick={submit} disabled={isPending || !campaignId || !defaultBudget || rules.length === 0}>
                            {isPending ? "Saving…" : "Save Schedule"}
                        </Button>
                        <Button variant="secondary" onClick={reset}>Cancel</Button>
                    </div>
                </div>
            )}
        </Card>
    );
};
