import { useState } from "react";
import { Button } from "../../../../components/ui/Button";
import { Card } from "../../../../components/ui/Card";
import { EmptyState } from "../../../../components/feedback/EmptyState";
import { Loading } from "../../../../components/feedback/Loading";
import { useAddBudgetSchedule, useBudgetSchedules, useDeleteBudgetSchedule, useToggleBudgetSchedule } from "../../hooks";

const SLOT_LABELS = {
    morning: "Morning 6–12",
    afternoon: "Afternoon 12–18",
    evening: "Evening 18–22",
    night: "Night 22–6",
};

export const ScheduleList = () => {
    const { data: schedules = [], isLoading } = useBudgetSchedules();
    const { mutate: remove, isPending: removing } = useDeleteBudgetSchedule();
    const { mutate: update, isPending: saving } = useAddBudgetSchedule();
    const { mutate: toggle, isPending: toggling } = useToggleBudgetSchedule();

    const [editingId, setEditingId] = useState(null);
    const [editForm, setEditForm] = useState({ name: "", default_budget: "" });

    const startEdit = (sched) => {
        setEditingId(sched.campaign_id);
        setEditForm({ name: sched.name || "", default_budget: String(sched.default_budget) });
    };

    const saveEdit = (sched) => {
        if (!editForm.default_budget) return;
        update(
            {
                ...sched,
                name: editForm.name.trim() || null,
                default_budget: parseFloat(editForm.default_budget),
            },
            { onSuccess: () => setEditingId(null) },
        );
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
                            sched.enabled !== false ? "border-border" : "border-border opacity-50"
                        }`}
                        >
                            {editingId === sched.campaign_id ? (
                                <div className="flex flex-col gap-3">
                                    <p className="text-xs font-semibold text-content">{sched.campaign_name}</p>
                                    <div className="grid grid-cols-2 gap-3">
                                        <div className="flex flex-col gap-1">
                                            <label className="text-xs text-content-muted">Schedule Name</label>
                                            <input
                                                type="text"
                                                value={editForm.name}
                                                onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                                                placeholder="e.g. Weekend Boost"
                                                className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                            />
                                        </div>
                                        <div className="flex flex-col gap-1">
                                            <label className="text-xs text-content-muted">Default Budget ₹</label>
                                            <input
                                                type="number"
                                                value={editForm.default_budget}
                                                onChange={(e) => setEditForm((f) => ({ ...f, default_budget: e.target.value }))}
                                                placeholder="e.g. 1000"
                                                className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                            />
                                        </div>
                                    </div>
                                    <div className="flex gap-2">
                                        <Button size="sm" disabled={saving} onClick={() => saveEdit(sched)}>
                                            {saving ? "Saving…" : "Save"}
                                        </Button>
                                        <Button variant="secondary" size="sm" onClick={() => setEditingId(null)}>
                                            Cancel
                                        </Button>
                                    </div>
                                </div>
                            ) : (
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    {sched.name && (
                                        <p className="text-xs font-semibold text-primary mb-0.5">{sched.name}</p>
                                    )}
                                    <p className="font-medium text-content">
                                        {sched.campaign_name}
                                    </p>
                                    <p className="mt-0.5 text-xs text-content-muted">
                                        ID: {sched.campaign_id} · Default: ₹
                                        {sched.default_budget.toLocaleString()}
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
                                        Remove
                                    </Button>
                                </div>
                            </div>
                            )}
                            {editingId !== sched.campaign_id && sched.rules.length > 0 && (
                                <div className="mt-3 flex flex-col gap-1.5">
                                    {sched.rules.map((rule, i) => (
                                        <div
                                            key={i}
                                            className="rounded bg-muted px-3 py-2 text-xs text-content-muted flex flex-col gap-0.5"
                                        >
                                            <div>
                                                <span className="mr-1">
                                                    {rule.type === "once" ? "📅" : "🔁"}
                                                </span>
                                                {rule.type === "once"
                                                    ? rule.date
                                                    : rule.days.join(", ")}
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
                                            </div>
                                            {(rule.start_date || rule.end_date) && (
                                                <div className="text-[10px] text-content-muted">
                                                    Valid: {rule.start_date || "any"} → {rule.end_date || "ongoing"}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </Card>
    );
};
