import { useState } from "react";
import { Card } from "../../../components/ui/Card";
import { CampaignStatusBadge } from "../../ads/components/CampaignStatusBadge";
import { useLiveCampaigns, useRestartCampaign, useStopCampaign } from "../hooks";

const ACTIVE_STATUSES = ["ACTIVE", "RUNNING", "SCHEDULED"];
const STOPPED_STATUSES = ["STOPPED"];

export const RestartCampaign = () => {
    const [open, setOpen] = useState(true);
    const [localStatus, setLocalStatus] = useState({});
    const { data: liveCampaigns, isLoading, refetch, isFetching, isError, error } = useLiveCampaigns();

    const restart = useRestartCampaign();
    const stop = useStopCampaign();

    const campaigns = liveCampaigns ?? [];
    const actionable = campaigns.filter((c) => {
        const s = (localStatus[c.campaign_id] ?? c.status)?.toUpperCase();
        return ACTIVE_STATUSES.includes(s) || STOPPED_STATUSES.includes(s);
    });

    const stoppedCount = actionable.filter((c) =>
        STOPPED_STATUSES.includes((localStatus[c.campaign_id] ?? c.status)?.toUpperCase())
    ).length;
    const activeCount = actionable.length - stoppedCount;

    return (
        <Card className="p-0 overflow-hidden">
            {/* ── Collapsible header ── */}
            <button
                onClick={() => setOpen((v) => !v)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/40 transition-colors"
            >
                <div className="flex items-center gap-3">
                    <span className="text-sm font-semibold text-content">Campaign Control</span>
                    <div className="flex items-center gap-1.5">
                        {activeCount > 0 && (
                            <span className="rounded-full bg-success/15 px-2 py-0.5 text-[11px] font-medium text-success">
                                {activeCount} active
                            </span>
                        )}
                        {stoppedCount > 0 && (
                            <span className="rounded-full bg-danger/15 px-2 py-0.5 text-[11px] font-medium text-danger">
                                {stoppedCount} stopped
                            </span>
                        )}
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={(e) => { e.stopPropagation(); refetch(); }}
                        disabled={isFetching}
                        className="rounded px-2 py-0.5 text-xs text-content-muted hover:text-primary disabled:opacity-40"
                        title="Refresh campaign list"
                    >
                        {isFetching ? "…" : "↻ Refresh"}
                    </button>
                    <span className="text-content-muted text-sm">{open ? "▲" : "▼"}</span>
                </div>
            </button>

            {/* ── Collapsible body ── */}
            {open && (
                <div className="border-t border-border px-4 py-3 flex flex-col gap-2">
                    {isLoading && (
                        <p className="text-sm text-content-muted">Connecting to Blinkit and fetching live status… (~20s)</p>
                    )}
                    {isError && (
                        <p className="text-sm text-danger">{error?.response?.data?.detail ?? "Failed to fetch live campaigns. Try refreshing."}</p>
                    )}
                    {!isLoading && !isError && actionable.length === 0 && (
                        <p className="text-sm text-content-muted">No active or stopped campaigns found.</p>
                    )}

                    {actionable.map((c) => {
                        const effectiveStatus = (localStatus[c.campaign_id] ?? c.status)?.toUpperCase();
                        const isStopped = STOPPED_STATUSES.includes(effectiveStatus);

                        const isRestarting = restart.isPending && restart.variables === c.campaign_id;
                        const isStopping = stop.isPending && stop.variables === c.campaign_id;
                        const restartErr = restart.isError && restart.variables === c.campaign_id;
                        const stopErr = stop.isError && stop.variables === c.campaign_id;

                        return (
                            <div
                                key={c.campaign_id}
                                className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2"
                            >
                                <div className="flex flex-col gap-0.5 min-w-0">
                                    <span className="truncate text-sm font-medium text-content">
                                        {c.name || `#${c.campaign_id}`}
                                    </span>
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <CampaignStatusBadge status={effectiveStatus} />
                                        <span className="text-xs text-content-muted font-mono">
                                            ID: {c.campaign_id}
                                        </span>
                                        {c.type && (
                                            <span className="text-xs text-content-muted">{c.type}</span>
                                        )}
                                    </div>
                                </div>

                                <div className="flex items-center gap-2 shrink-0">
                                    {(restartErr || stopErr) && (
                                        <span className="text-xs text-danger">
                                            {restartErr
                                                ? (restart.error?.response?.data?.detail ?? "Restart failed")
                                                : (stop.error?.response?.data?.detail ?? "Stop failed")}
                                        </span>
                                    )}

                                    {isStopped ? (
                                        <button
                                            disabled={restart.isPending || stop.isPending}
                                            onClick={() => {
                                                restart.reset();
                                                restart.mutate(c.campaign_id, {
                                                    onSuccess: () => setLocalStatus((p) => ({ ...p, [c.campaign_id]: "ACTIVE" })),
                                                });
                                            }}
                                            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary/90 disabled:opacity-50"
                                        >
                                            {isRestarting ? "Restarting… (~20s)" : "↺ Restart"}
                                        </button>
                                    ) : (
                                        <button
                                            disabled={restart.isPending || stop.isPending}
                                            onClick={() => {
                                                stop.reset();
                                                stop.mutate(c.campaign_id, {
                                                    onSuccess: () => setLocalStatus((p) => ({ ...p, [c.campaign_id]: "STOPPED" })),
                                                });
                                            }}
                                            className="rounded-md bg-danger px-3 py-1.5 text-xs font-medium text-white hover:bg-danger/90 disabled:opacity-50"
                                        >
                                            {isStopping ? "Stopping… (~20s)" : "⏹ Stop"}
                                        </button>
                                    )}
                                </div>
                            </div>
                        );
                    })}

                    {(restart.isPending || stop.isPending) && (
                        <p className="text-xs text-content-muted">
                            Connecting to Blinkit… this takes ~20 seconds.
                        </p>
                    )}
                </div>
            )}
        </Card>
    );
};
