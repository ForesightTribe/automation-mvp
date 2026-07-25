import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Loading } from "../../../components/feedback/Loading";
import { useAddBudgetSchedule, useBudgetSchedules, useDeleteBudgetSchedule, useToggleBudgetSchedule } from "../hooks";
import { EditScheduleForm } from "./EditScheduleForm";

const SLOT_LABELS = {
    morning: "Morning 6–12",
    afternoon: "Afternoon 12–18",
    evening: "Evening 18–22",
    night: "Night 22–6",
};

const getISTToday = () => {
    const ist = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    const yyyy = ist.getFullYear();
    const mo   = String(ist.getMonth() + 1).padStart(2, "0");
    const dd   = String(ist.getDate()).padStart(2, "0");
    const hh   = String(ist.getHours()).padStart(2, "0");
    const mm   = String(ist.getMinutes()).padStart(2, "0");
    return { today: `${yyyy}-${mo}-${dd}`, currentTime: `${hh}:${mm}` };
};

const isRuleExpired = (rule) => {
    if (rule.type !== "once") return false;
    const { today, currentTime } = getISTToday();
    const ruleDate = rule.date;
    if (!ruleDate) return false;

    if (ruleDate > today) return false; // future date — not expired

    const st = rule.start_time;
    const et = rule.end_time;

    if (ruleDate < today) {
        // Overnight rule (e.g. 19:00–02:00): extends into the next calendar day
        if (st && et && et <= st) {
            const [y, m, d] = ruleDate.split("-").map(Number);
            const nd = new Date(y, m - 1, d + 1);
            const nextDay = `${nd.getFullYear()}-${String(nd.getMonth()+1).padStart(2,"0")}-${String(nd.getDate()).padStart(2,"0")}`;
            if (today === nextDay && currentTime < et) return false; // still within overnight window
        }
        return true; // date is in the past and overnight window (if any) has ended
    }

    // ruleDate === today: expired only if end_time has passed
    if (et && et > (st || "00:00") && currentTime >= et) return true;
    return false;
};

export const ScheduleList = () => {
    const { data: schedules = [], isLoading } = useBudgetSchedules();
    const { mutate: remove, isPending: removing } = useDeleteBudgetSchedule();
    const { mutate: update, isPending: saving } = useAddBudgetSchedule();
    const { mutate: toggle, isPending: toggling } = useToggleBudgetSchedule();

    const [editingId, setEditingId] = useState(null);

    const startEdit = (sched) => setEditingId(sched.campaign_id);

    const saveEdit = (updatedSchedule) => {
        update(updatedSchedule, { onSuccess: () => setEditingId(null) });
    };

    if (isLoading) return <Loading label="Loading schedules…" />;

    return (
        <Card title="Active Budget Schedules">
            {schedules.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="flex flex-col gap-3">
                    {schedules.map((sched) => (
                        <div
                            key={sched.campaign_id}
                            className={`rounded-lg border p-4 transition-opacity ${
                            sched.enabled !== false ? "border-border" : "border-border/50 opacity-60"
                        }`}
                        >
                            {editingId === sched.campaign_id ? (
                                <EditScheduleForm
                                    schedule={sched}
                                    onSave={saveEdit}
                                    onCancel={() => setEditingId(null)}
                                    isPending={saving}
                                />
                            ) : (
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <div className="flex items-center gap-2 flex-wrap mb-0.5">
                                        {sched.name && (
                                            <p className="text-xs font-semibold text-primary">{sched.name}</p>
                                        )}
                                        {sched.enabled === false && (
                                            <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-semibold text-warning">
                                                PAUSED
                                            </span>
                                        )}
                                    </div>
                                    <p className="font-medium text-content">
                                        {sched.campaign_name}
                                    </p>
                                    <p className="mt-0.5 text-xs text-content-muted">
                                        ID: {sched.campaign_id} · Default: ₹{sched.default_budget.toLocaleString()}
                                        {sched.enabled === false && (
                                            <span className="ml-2 italic">· scheduler skipping this campaign</span>
                                        )}
                                    </p>
                                </div>
                                <div className="flex gap-2">
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        disabled={toggling}
                                        onClick={() => toggle(sched.campaign_id)}
                                    >
                                        {sched.enabled !== false ? "Pause" : "Resume"}
                                    </Button>
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        onClick={() => startEdit(sched)}
                                    >
                                        Edit
                                    </Button>
                                    <Button
                                        variant="danger"
                                        size="sm"
                                        disabled={removing}
                                        onClick={() => remove(sched.campaign_id)}
                                    >
                                        Delete
                                    </Button>
                                </div>
                            </div>
                            )}
                            {editingId !== sched.campaign_id && sched.rules.length > 0 && (
                                <div className="mt-3 flex flex-col gap-1.5">
                                    {sched.rules.map((rule, i) => {
                                        const done = isRuleExpired(rule);
                                        return (
                                            <div
                                                key={i}
                                                className="rounded bg-muted px-3 py-2 text-xs text-content-muted flex flex-col gap-0.5"
                                            >
                                                <div className="flex items-center gap-2 flex-wrap">
                                                    <span>
                                                        <span className="mr-1">{rule.type === "once" ? "📅" : "🔁"}</span>
                                                        {rule.type === "once"
                                                            ? rule.date
                                                            : (rule.days.length ? rule.days.join(", ") : "every day")}
                                                        {rule.time_slots?.length > 0 && (
                                                            <> · {rule.time_slots.map((s) => SLOT_LABELS[s] || s).join(", ")}</>
                                                        )}
                                                        {(rule.start_time || rule.end_time) && (
                                                            <> · {rule.start_time || "—"}–{rule.end_time || "—"}</>
                                                        )}
                                                        {" → "}
                                                        <span className="font-semibold text-content">
                                                            ₹{rule.budget.toLocaleString()}
                                                        </span>
                                                    </span>
                                                    {done && (
                                                        <span className="rounded-full bg-success/15 px-2 py-0.5 text-[10px] font-semibold text-success">
                                                            DONE
                                                        </span>
                                                    )}
                                                </div>
                                                {(rule.start_date || rule.end_date) && rule.type !== "once" && (
                                                    <div className="text-[10px] text-content-muted">
                                                        Valid: {rule.start_date || "any"} → {rule.end_date || "ongoing"}
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </Card>
    );
};



