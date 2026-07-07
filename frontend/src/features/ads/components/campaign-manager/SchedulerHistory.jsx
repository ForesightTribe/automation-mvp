import { Card } from "../../../../components/ui/Card";
import { DataTable } from "../../../../components/ui/DataTable";
import { EmptyState } from "../../../../components/feedback/EmptyState";
import { Loading } from "../../../../components/feedback/Loading";
import { useSchedulerHistory } from "../../hooks";

const columns = [
    { key: "timestamp", label: "Time (IST)" },
    { key: "campaign_name", label: "Campaign" },
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
    const { data: log = [], isLoading } = useSchedulerHistory();

    if (isLoading) return <Loading label="Loading history…" />;

    return (
        <Card title="Scheduler History">
            {log.length === 0 ? (
                <EmptyState />
            ) : (
                <DataTable
                    columns={columns}
                    rows={log}
                    rowKey={(r, i) => `${i}-${r.timestamp}-${r.campaign_name}`}
                    maxHeight={400}
                />
            )}
        </Card>
    );
};
