import { useState } from "react";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Loading } from "../../../components/feedback/Loading";
import { useBidOptimizerHistory } from "../hooks";

function friendlyAction(entry) {
    const a = entry.action || "";

    if (a.startsWith("↑")) {
        // e.g. "↑ pos 13.0 > target 5 | LIVE-Ad(...) | impressions=5 | step Rs100 | Rs401->Rs501"
        const posMatch = a.match(/pos\s+([\d.]+)/);
        const targetMatch = a.match(/target\s+(\d+)/);
        const pos = posMatch ? `#${Math.round(posMatch[1])}` : null;
        const target = targetMatch ? `#${targetMatch[1]}` : null;
        return {
            label: pos && target
                ? `Raised bid — at position ${pos}, targeting ${target}`
                : "Raised bid to improve position",
            color: "text-warning",
            icon: "↑",
        };
    }

    if (a.startsWith("↓")) {
        const posMatch = a.match(/pos\s+([\d.]+)/);
        const targetMatch = a.match(/target\s+(\d+)/);
        const pos = posMatch ? `#${Math.round(posMatch[1])}` : null;
        const target = targetMatch ? `#${targetMatch[1]}` : null;
        return {
            label: pos && target
                ? `Lowered bid — at position ${pos}, targeting ${target}`
                : "Lowered bid",
            color: "text-primary",
            icon: "↓",
        };
    }

    if (a.startsWith("HOLD")) {
        const posMatch = a.match(/pos\s+([\d.]+)/);
        const pos = posMatch ? `#${Math.round(posMatch[1])}` : null;
        return {
            label: pos ? `Holding bid — position stable at ${pos}` : "Holding bid — position stable",
            color: "text-content-muted",
            icon: "–",
        };
    }

    if (a.startsWith("COOLDOWN")) {
        return {
            label: "Cooling down — waiting for last bid change to settle",
            color: "text-content-muted",
            icon: "⏱",
        };
    }

    if (a.startsWith("SKIP")) {
        const isNotFound = a.toLowerCase().includes("not found");
        return {
            label: isNotFound
                ? "Product not found in live search results"
                : "Skipped — no action needed",
            color: "text-warning",
            icon: "○",
        };
    }

    if (a.startsWith("ERROR") || !entry.success) {
        return { label: a || "Error", color: "text-danger", icon: "✗" };
    }

    if (a.startsWith("✓")) {
        return { label: "Applied successfully", color: "text-success", icon: "✓" };
    }

    return { label: a, color: "text-content", icon: "•" };
}

export const BidOptimizerHistory = () => {
    const [open, setOpen] = useState(false);
    const { data: entries = [], isLoading } = useBidOptimizerHistory();

    const chevron = (
        <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-1 text-xs text-content-muted hover:text-content transition-colors"
        >
            {entries.length > 0 && (
                <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium">
                    {entries.length}
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
        <Card title="Bid Optimizer History" actions={chevron}>
            {open && (
                isLoading ? (
                    <Loading label="Loading history…" />
                ) : entries.length === 0 ? (
                    <EmptyState />
                ) : (
                    <div className="overflow-x-auto overflow-y-auto max-h-80">
                        <table className="w-full text-xs">
                            <thead>
                                <tr className="border-b border-border text-left text-content-muted">
                                    <th className="py-2 pr-4 font-medium">Time (IST)</th>
                                    <th className="py-2 pr-4 font-medium">Campaign</th>
                                    <th className="py-2 pr-4 font-medium">Keyword</th>
                                    <th className="py-2 pr-4 font-medium">What happened</th>
                                    <th className="py-2 pr-4 font-medium text-right">Bid (CPM)</th>
                                    <th className="py-2 font-medium text-right">Result</th>
                                </tr>
                            </thead>
                            <tbody>
                                {entries.map((entry, i) => {
                                    const { label, color, icon } = friendlyAction(entry);
                                    return (
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
                                            <td className={`py-2 pr-4 max-w-72 ${color}`}>
                                                <span className="font-medium mr-1">{icon}</span>
                                                {label}
                                            </td>
                                            <td className="py-2 pr-4 text-right text-content-muted whitespace-nowrap">
                                                {entry.old_cpm != null && entry.new_cpm != null
                                                    ? entry.old_cpm !== entry.new_cpm
                                                        ? `₹${entry.old_cpm} → ₹${entry.new_cpm}`
                                                        : `₹${entry.new_cpm}`
                                                    : "—"}
                                            </td>
                                            <td className="py-2 text-right">
                                                {entry.success
                                                    ? <span className="text-success">✓</span>
                                                    : <span className="text-danger">✗</span>}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )
            )}
        </Card>
    );
};
