import { useState } from "react";
import { Button } from "../../../components/ui/Button";

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

const windowMinutes = (start, end) => {
    if (!start || !end) return null;
    const [sh, sm] = start.split(":").map(Number);
    const [eh, em] = end.split(":").map(Number);
    const diff = (eh * 60 + em) - (sh * 60 + sm);
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

// Returns current IST time info
const getISTNow = () => {
    const now = new Date();
    const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    const hh = String(ist.getHours()).padStart(2, "0");
    const mm = String(ist.getMinutes()).padStart(2, "0");
    const yyyy = ist.getFullYear();
    const mo = String(ist.getMonth() + 1).padStart(2, "0");
    const dd = String(ist.getDate()).padStart(2, "0");
    const dayNames = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
    return {
        currentTime: `${hh}:${mm}`,
        today: `${yyyy}-${mo}-${dd}`,
        dayName: dayNames[ist.getDay()],
    };
};

const isRuleActive = (rule) => {
    if (!rule.start_time) return false;
    const { currentTime, today, dayName } = getISTNow();

    if (rule.type === "once") {
        if (rule.date !== today) return false;
    } else {
        if (rule.days.length && !rule.days.includes(dayName)) return false;
        if (rule.start_date && today < rule.start_date) return false;
        if (rule.end_date && today > rule.end_date) return false;
    }

    const start = rule.start_time;
    const end = rule.end_time;
    if (!end) return currentTime >= start;
    if (end <= start) return currentTime >= start || currentTime < end; // overnight
    return currentTime >= start && currentTime < end;
};

export const EditScheduleForm = ({ schedule, onSave, onCancel, isPending }) => {
    const [scheduleName, setScheduleName] = useState(schedule.name || "");
    const [defaultBudget, setDefaultBudget] = useState(String(schedule.default_budget));
    const [rules, setRules] = useState(
        (schedule.rules || []).map((r) => ({ ...r, budget: String(r.budget) }))
    );

    const [rule, setRule] = useState(emptyRule());
    const [ruleOpen, setRuleOpen] = useState(false);
    const [ruleError, setRuleError] = useState("");

    const updateRuleField = (idx, field, value) =>
        setRules((rs) => rs.map((r, i) => i === idx ? { ...r, [field]: value } : r));

    const updateRuleBudget = (idx, value) => updateRuleField(idx, "budget", value);

    const removeRule = (idx) =>
        setRules((rs) => rs.filter((_, i) => i !== idx));

    const toggleDay = (day) =>
        setRule((r) => ({
            ...r,
            days: r.days.includes(day) ? r.days.filter((d) => d !== day) : [...r.days, day],
        }));

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
            if (!rule.date) { setRuleError("Please select a date."); return; }
            for (let i = 0; i < rule.time_ranges.length; i++) {
                if (!rule.time_ranges[i].start_time) {
                    setRuleError(`Time slot ${i + 1}: Start time is required.`); return;
                }
            }
            const newRules = rule.time_ranges.map((tr) => ({
                type: "once", days: [], time_slots: [],
                budget: String(rule.budget),
                date: rule.date, start_date: null, end_date: null,
                start_time: tr.start_time, end_time: tr.end_time || null,
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
            const newRules = rule.time_ranges.map((tr) => ({
                type: "recurring", days: rule.days, time_slots: [],
                budget: String(rule.budget),
                date: null, start_date: rule.start_date, end_date: rule.end_date || null,
                start_time: tr.start_time, end_time: tr.end_time || null,
            }));
            setRules((rs) => [...rs, ...newRules]);
        }

        setRule(emptyRule());
        setRuleError("");
        setRuleOpen(false);
    };

    const submit = () => {
        if (!defaultBudget) return;
        onSave({
            ...schedule,
            name: scheduleName.trim() || null,
            default_budget: parseFloat(defaultBudget),
            rules: rules.map((r) => ({ ...r, budget: parseFloat(r.budget) || 0 })),
        });
    };

    return (
        <div className="flex flex-col gap-4">
            <p className="text-xs font-semibold text-content">{schedule.campaign_name}</p>

            {/* Name + Default Budget */}
            <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                    <label className="text-xs text-content-muted">Schedule Name</label>
                    <input
                        type="text"
                        value={scheduleName}
                        onChange={(e) => setScheduleName(e.target.value)}
                        placeholder="e.g. Weekend Boost"
                        className={inputCls}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <label className="text-xs text-content-muted">Default Budget ₹ <span className="text-danger">*</span></label>
                    <input
                        type="number"
                        value={defaultBudget}
                        onChange={(e) => setDefaultBudget(e.target.value)}
                        placeholder="e.g. 1000"
                        className={inputCls}
                    />
                </div>
            </div>

            {/* Rules list */}
            {rules.length > 0 && (
                <div className="flex flex-col gap-2">
                    <p className="text-xs font-medium text-content-muted">Rules ({rules.length}):</p>
                    {rules.map((r, i) => {
                        const active = isRuleActive(r);
                        return (
                            <div
                                key={i}
                                className={`rounded-lg border px-3 py-2.5 text-xs ${
                                    active
                                        ? "border-success/40 bg-success/5"
                                        : "border-border bg-muted/40"
                                }`}
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div className="flex flex-col gap-1.5 flex-1">
                                        {/* Rule label */}
                                        <div className="flex items-center gap-1.5 flex-wrap">
                                            {active && (
                                                <span className="rounded-full bg-success/15 px-2 py-0.5 text-[10px] font-semibold text-success">
                                                    🟢 Active now
                                                </span>
                                            )}
                                            <span className="text-content-muted">
                                                {r.type === "once"
                                                    ? `📅 ${r.date}`
                                                    : `🔁 ${r.days.length ? r.days.map(d => d.slice(0, 3)).join(", ") : "every day"}`}
                                                {r.start_date && (
                                                    <span> · {r.start_date}{r.end_date ? ` → ${r.end_date}` : " onwards"}</span>
                                                )}
                                            </span>
                                        </div>

                                        {/* Time + Budget inline */}
                                        <div className="flex items-center gap-2 flex-wrap">
                                            {active ? (
                                                /* Time locked when active */
                                                <span className="flex items-center gap-1 text-content-muted">
                                                    🔒 {r.start_time}{r.end_time ? `–${r.end_time}` : "+"}
                                                    <span className="text-[10px] text-warning ml-1">(locked while active)</span>
                                                </span>
                                            ) : (
                                                /* Time editable when not active */
                                                <div className="flex items-center gap-1">
                                                    <input
                                                        type="time"
                                                        value={r.start_time || ""}
                                                        onChange={(e) => updateRuleField(i, "start_time", e.target.value)}
                                                        className="rounded border border-border bg-card px-2 py-0.5 text-xs text-content outline-none focus:border-primary"
                                                    />
                                                    <span className="text-content-muted">–</span>
                                                    <input
                                                        type="time"
                                                        value={r.end_time || ""}
                                                        onChange={(e) => updateRuleField(i, "end_time", e.target.value)}
                                                        className="rounded border border-border bg-card px-2 py-0.5 text-xs text-content outline-none focus:border-primary"
                                                    />
                                                </div>
                                            )}

                                            <span className="text-content-muted">→ ₹</span>

                                            {/* Budget — always editable */}
                                            <input
                                                type="number"
                                                value={r.budget}
                                                onChange={(e) => updateRuleBudget(i, e.target.value)}
                                                className="w-28 rounded border border-border bg-card px-2 py-0.5 text-sm text-content outline-none focus:border-primary"
                                            />
                                        </div>
                                    </div>

                                    {/* Delete — disabled if active */}
                                    <button
                                        onClick={() => removeRule(i)}
                                        disabled={active}
                                        title={active ? "Cannot delete an active rule" : "Remove rule"}
                                        className={`shrink-0 text-base ${
                                            active
                                                ? "opacity-25 cursor-not-allowed"
                                                : "text-danger hover:opacity-75"
                                        }`}
                                    >
                                        ✕
                                    </button>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Add new rule */}
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

                    <div className="flex gap-4">
                        {[
                            { value: "recurring", label: "Recurring (weekly)" },
                            { value: "once", label: "One-time (specific date)" },
                        ].map(({ value, label }) => (
                            <label key={value} className="flex cursor-pointer items-center gap-1.5 text-xs">
                                <input
                                    type="radio"
                                    checked={rule.type === value}
                                    onChange={() => setRule({ ...emptyRule(), type: value })}
                                />
                                <span className="text-content">{label}</span>
                            </label>
                        ))}
                    </div>

                    {rule.type === "once" && (
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-content-muted">Date <span className="text-danger">*</span></label>
                            <input type="date" value={rule.date} onChange={(e) => setRule((r) => ({ ...r, date: e.target.value }))} className={inputCls} />
                        </div>
                    )}

                    {rule.type === "recurring" && (
                        <div className="grid grid-cols-2 gap-3">
                            <div className="flex flex-col gap-1">
                                <label className="text-xs text-content-muted">Start Date <span className="text-danger">*</span></label>
                                <input type="date" value={rule.start_date} onChange={(e) => setRule((r) => ({ ...r, start_date: e.target.value }))} className={inputCls} />
                            </div>
                            <div className="flex flex-col gap-1">
                                <label className="text-xs text-content-muted">End Date (optional)</label>
                                <input type="date" value={rule.end_date} onChange={(e) => setRule((r) => ({ ...r, end_date: e.target.value }))} className={inputCls} />
                            </div>
                        </div>
                    )}

                    {rule.type === "recurring" && (
                        <div className="flex flex-col gap-1.5">
                            <p className="text-xs font-medium text-content-muted">Days <span className="text-danger">*</span></p>
                            <div className="flex flex-wrap gap-2">
                                <Toggle
                                    label="All"
                                    checked={rule.days.length === DAYS.length}
                                    onChange={() => setRule((r) => ({ ...r, days: r.days.length === DAYS.length ? [] : [...DAYS] }))}
                                />
                                <span className="text-content-muted">|</span>
                                {DAYS.map((d) => (
                                    <Toggle key={d} label={d.slice(0, 3)} checked={rule.days.includes(d)} onChange={() => toggleDay(d)} />
                                ))}
                            </div>
                        </div>
                    )}

                    <div className="flex flex-col gap-2">
                        <p className="text-xs font-medium text-content-muted">Time Slots <span className="text-danger">*</span></p>
                        {rule.time_ranges.map((tr, idx) => {
                            const mins = windowMinutes(tr.start_time, tr.end_time);
                            const tooShort = mins !== null && mins < 6;
                            return (
                                <div key={idx} className="flex flex-col gap-1">
                                    <div className="flex items-end gap-2">
                                        <div className="flex flex-1 flex-col gap-1">
                                            <label className="text-[10px] text-content-muted">Start Time <span className="text-danger">*</span></label>
                                            <input type="time" value={tr.start_time} onChange={(e) => updateTimeRange(idx, "start_time", e.target.value)} className={inputCls} />
                                        </div>
                                        <div className="flex flex-1 flex-col gap-1">
                                            <label className="text-[10px] text-content-muted">End Time <span className="text-danger">*</span></label>
                                            <input type="time" value={tr.end_time} onChange={(e) => updateTimeRange(idx, "end_time", e.target.value)} className={inputCls} />
                                        </div>
                                        {rule.time_ranges.length > 1 && (
                                            <button onClick={() => removeTimeRange(idx)} className="mb-1.5 text-sm text-danger hover:opacity-75">✕</button>
                                        )}
                                    </div>
                                    {tooShort && (
                                        <p className="text-[11px] text-warning">⚠ Window is only {mins} min — keep at least 6 min to be safe.</p>
                                    )}
                                </div>
                            );
                        })}
                        {rule.time_ranges[rule.time_ranges.length - 1]?.start_time && (
                            <button onClick={addTimeRange} className="self-start text-xs text-primary hover:underline">
                                + Add another time slot
                            </button>
                        )}
                    </div>

                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">Budget ₹ <span className="text-danger">*</span></label>
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
                        <Button variant="ghost" size="sm" onClick={() => { setRule(emptyRule()); setRuleError(""); setRuleOpen(false); }}>Cancel</Button>
                    </div>
                </div>
            )}

            <div className="flex gap-2 pt-1 border-t border-border">
                <Button onClick={submit} disabled={isPending || !defaultBudget}>
                    {isPending ? "Saving…" : "Save Changes"}
                </Button>
                <Button variant="secondary" onClick={onCancel}>Cancel</Button>
            </div>
        </div>
    );
};
