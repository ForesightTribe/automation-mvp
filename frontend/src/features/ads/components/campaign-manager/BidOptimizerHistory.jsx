import { Card } from "../../../../components/ui/Card";
import { EmptyState } from "../../../../components/feedback/EmptyState";
import { Loading } from "../../../../components/feedback/Loading";
import { useBidOptimizerHistory } from "../../hooks";

const resultColor = (entry) => {
    if (!entry.success) return "text-danger";
    const a = entry.action || "";
    if (a.startsWith("✓")) return "text-success";
    if (a.startsWith("COOLDOWN")) return "text-content-muted";
    if (a.startsWith("ERROR")) return "text-danger";
    if (a.startsWith("SKIP")) return "text-warning";
    if (a.startsWith("↑")) return "text-warning";
    if (a.startsWith("↓")) return "text-primary";
    return "text-content";
};

export const BidOptimizerHistory = () => {
    const { data: entries = [], isLoading } = useBidOptimizerHistory();

    if (isLoading) return <Loading label="Loading history…" />;

    return (
        <Card title="Bid Optimizer History">
            {entries.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead>
                            <tr className="border-b border-border text-left text-content-muted">
                                <th className="py-2 pr-4 font-medium">Time (IST)</th>
                                <th className="py-2 pr-4 font-medium">Campaign</th>
                                <th className="py-2 pr-4 font-medium">Keyword</th>
                                <th className="py-2 pr-4 font-medium">Action</th>
                                <th className="py-2 pr-4 font-medium text-right">CPM</th>
                                <th className="py-2 font-medium text-right">Result</th>
                            </tr>
                        </thead>
                        <tbody>
                            {entries.map((entry, i) => (
                                <tr key={i} className="border-b border-border/50 last:border-0">
                                    <td className="py-2 pr-4 text-content-muted whitespace-nowrap">
                                        {entry.timestamp}
                                    </td>
                                    <td className="py-2 pr-4 text-content max-w-40 truncate">
                                        {entry.campaign_name}
                                    </td>
                                    <td className="py-2 pr-4 font-medium text-content">
                                        {entry.keyword ?? "—"}
                                    </td>
                                    <td className={`py-2 pr-4 max-w-75 ${resultColor(entry)}`}>
                                        {entry.action}
                                        {entry.detail && (
                                            <div className="mt-0.5 text-danger text-xs opacity-80">{entry.detail}</div>
                                        )}
                                    </td>
                                    <td className="py-2 pr-4 text-right text-content-muted whitespace-nowrap">
                                        {entry.old_cpm != null && entry.new_cpm != null
                                            ? `₹${entry.old_cpm} → ₹${entry.new_cpm}`
                                            : "—"}
                                    </td>
                                    <td className="py-2 text-right">
                                        {entry.success
                                            ? <span className="text-success">✓</span>
                                            : <span className="text-danger">✗</span>}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </Card>
    );
};

