import { useState } from "react";
import { Card } from "../../../components/ui/Card";
import { DataTable } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Loading } from "../../../components/feedback/Loading";
import { useSchedulerHistory } from "../hooks";

const columns = [
    { key: "timestamp", label: "Time (IST)" },
    { key: "campaign_name", label: "Campaign" },
    {
        key: "schedule_name",
        label: "Schedule",
        render: (r) => r.schedule_name
            ? <span className="font-medium text-content">{r.schedule_name}</span>
            : <span className="text-content-muted italic">—</span>,
    },
    {
        key: "budget_applied",
        label: "Budget",
        align: "right",
        render: (r) => `₹${r.budget_applied.toLocaleString()}`,
    },
    { key: "rule", label: "Rule" },
    {
        key: "success",
        label: "Result",
        render: (r) =>
            r.success ? (
                <span className="text-success">✓ done</span>
            ) : (
                <span className="text-danger">✗ failed</span>
            ),
    },
];

export const SchedulerHistory = () => {
    const [open, setOpen] = useState(false);
    const { data: log = [], isLoading } = useSchedulerHistory();

    const passed = log.filter((r) => r.success).length;
    const failed = log.filter((r) => !r.success).length;

    const chevron = (
        <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 text-xs text-content-muted hover:text-content transition-colors"
        >
            {log.length > 0 && (
                <span className="flex items-center gap-1.5">
                    {passed > 0 && (
                        <span className="rounded-full bg-success/15 px-1.5 py-0.5 text-[10px] font-medium text-success">
                            ✓ {passed}
                        </span>
                    )}
                    {failed > 0 && (
                        <span className="rounded-full bg-danger/15 px-1.5 py-0.5 text-[10px] font-medium text-danger">
                            ✗ {failed}
                        </span>
                    )}
                </span>
            )}
            <span
                className="transition-transform duration-200"
                style={{ display: "inline-block", transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
            >
                ▾
            </span>
        </button>
    );

    return (
        <Card title="Scheduler History" actions={chevron}>
            {open && (
                isLoading ? (
                    <Loading label="Loading history…" />
                ) : log.length === 0 ? (
                    <EmptyState />
                ) : (
                    <DataTable
                        columns={columns}
                        rows={log}
                        rowKey={(r, i) => `${i}-${r.timestamp}-${r.campaign_name}`}
                        maxHeight={400}
                    />
                )
            )}
        </Card>
    );
};
