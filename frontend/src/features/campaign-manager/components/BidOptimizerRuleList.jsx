import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { Loading } from "../../../components/feedback/Loading";
import { useBidOptimizerRules, useDeleteBidOptimizerRule, useToggleBidOptimizerRule } from "../hooks";

const positionStatus = (rule) => {
    const pos = rule.last_position;
    const target = rule.target_position;
    if (pos == null) return null;
    const dist = Math.abs(pos - target).toFixed(1);
    if (pos < target) return { label: `#${pos} (↓ ${dist} ahead of target)`, color: "text-success" };
    if (pos > target) return { label: `#${pos} (↑ ${dist} behind target)`, color: "text-warning" };
    return { label: `#${pos} (on target ✓)`, color: "text-success" };
};

export const BidOptimizerRuleList = () => {
    const { data: rules = [], isLoading } = useBidOptimizerRules();
    const { mutate: remove, isPending: removing } = useDeleteBidOptimizerRule();
    const { mutate: toggle, isPending: toggling } = useToggleBidOptimizerRule();

    if (isLoading) return <Loading label="Loading rules…" />;

    return (
        <Card title="Active Bid Rules">
            {rules.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="flex flex-col gap-3">
                    {rules.map((rule) => (
                        <div
                            key={rule.id}
                            className={`rounded-lg border p-4 transition-opacity ${
                                rule.active ? "border-border" : "border-border opacity-50"
                            }`}
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex flex-col gap-0.5">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <p className="font-medium text-content">{rule.campaign_name}</p>
                                        {rule.location_name ? (
                                            <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs text-success">
                                                📍 {rule.location_name}
                                            </span>
                                        ) : rule.lat ? (
                                            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">
                                                📍 {rule.lat},{rule.lon}
                                            </span>
                                        ) : (
                                            <span className="rounded-full bg-warning/10 px-2 py-0.5 text-xs text-warning">
                                                ⚠ no location — live position may be inaccurate
                                            </span>
                                        )}
                                    </div>
                                    <p className="text-xs text-content-muted">ID: {rule.campaign_id}</p>
                                </div>
                                <div className="flex gap-2">
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        disabled={toggling}
                                        onClick={() => toggle(rule.id)}
                                    >
                                        {rule.active ? "Pause" : "Resume"}
                                    </Button>
                                    <Button
                                        variant="danger"
                                        size="sm"
                                        disabled={removing}
                                        onClick={() => remove(rule.id)}
                                    >
                                        Delete
                                    </Button>
                                </div>
                            </div>

                            {/* Keyword row */}
                            <div className="mt-3 rounded-md bg-muted px-3 py-2 text-xs">
                                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                                    <span>
                                        <span className="text-content-muted">Keyword: </span>
                                        <span className="font-semibold text-content">{rule.keyword}</span>
                                        <span className="ml-1 text-content-muted">({rule.match_type})</span>
                                    </span>
                                    <span>
                                        <span className="text-content-muted">Target: </span>
                                        <span className="font-semibold text-content">#{rule.target_position}</span>
                                    </span>
                                    <span>
                                        <span className="text-content-muted">Bid range: </span>
                                        <span className="font-semibold text-content">
                                            ₹{rule.min_bid.toLocaleString()} – ₹{rule.max_bid.toLocaleString()}
                                        </span>
                                    </span>
                                    {rule.last_cpm && (
                                        <span>
                                            <span className="text-content-muted">CPM: </span>
                                            <span className="font-semibold text-primary">₹{rule.last_cpm.toLocaleString()}</span>
                                        </span>
                                    )}
                                    {(() => {
                                        const s = positionStatus(rule);
                                        return s ? (
                                            <span>
                                                <span className="text-content-muted">Position: </span>
                                                <span className={`font-semibold ${s.color}`}>{s.label}</span>
                                            </span>
                                        ) : (
                                            <span className="text-content-muted italic">Position: no data yet</span>
                                        );
                                    })()}
                                </div>

                                {/* Schedule */}
                                {(rule.start_time || rule.start_date) && (
                                    <div className="mt-1.5 text-content-muted">
                                        {rule.start_date && (
                                            <span className="mr-3">
                                                📅 {rule.start_date}{rule.stop_date ? ` → ${rule.stop_date}` : ""}
                                            </span>
                                        )}
                                        {rule.start_time && (
                                            <span>
                                                🕐 {rule.start_time} – {rule.stop_time || "?"}
                                            </span>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </Card>
    );
};



