import { useState, useEffect } from "react";
import { useCampaigns } from "../hooks";

const TYPE_LABELS = {
    PRODUCT_LISTING: "Product Listing",
    PRODUCT_RECOMMENDATION: "Product Recommendation",
    SEARCH_SUGGESTION: "Search Suggestion",
    SHELF_DIY: "Shelf",
    STORY_DIY: "Story",
    BANNER_DIY: "Banner",
    BRAND_SPOTLIGHT_DIY: "Brand Spotlight",
    BANNER_LISTING: "Banner Listing",
    BRAND_BOOSTER: "Brand Booster",
};

const labelFor = (type) => TYPE_LABELS[type] || type || "Other";

/**
 * Searchable campaign selector with visible list.
 * Props:
 *   value        – selected campaign_id (string)
 *   onChange     – (campaign_id: string, campaign_name: string) => void
 *   onReset      – called when selection is cleared (optional)
 */
export const CampaignSelector = ({ value, onChange, onReset }) => {
    const { data: campaignsPage } = useCampaigns();
    const campaigns = campaignsPage?.items ?? [];

    const [search, setSearch] = useState("");
    const [open, setOpen] = useState(false);

    const filtered = search.trim()
        ? campaigns.filter((c) => c.name?.toLowerCase().includes(search.trim().toLowerCase()))
        : campaigns;

    const selected = campaigns.find((c) => String(c.campaign_id) === String(value));

    const handleSelect = (c) => {
        onChange(String(c.campaign_id), c.name ?? "");
        setSearch("");
        setOpen(false);
    };

    const handleClear = () => {
        onChange("", "");
        setSearch("");
        setOpen(false);
        onReset?.();
    };

    // If value is cleared externally, reset search
    useEffect(() => {
        if (!value) { setSearch(""); setOpen(false); }
    }, [value]);

    return (
        <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-content-muted">Campaign</label>

            {/* Selected campaign pill */}
            {selected && !open ? (
                <div className="flex items-center justify-between rounded-md border border-primary bg-primary/5 px-3 py-2">
                    <div className="flex flex-col">
                        <span className="text-sm font-medium text-content">{selected.name}</span>
                        <span className="text-[10px] text-content-muted">
                            ID: {selected.campaign_id} · {labelFor(selected.type)}
                        </span>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => setOpen(true)}
                            className="text-xs text-primary hover:underline"
                        >
                            Change
                        </button>
                        <button
                            onClick={handleClear}
                            className="text-xs text-danger hover:underline"
                        >
                            Clear
                        </button>
                    </div>
                </div>
            ) : (
                <div className="flex flex-col gap-1">
                    {/* Search input */}
                    <input
                        type="text"
                        value={search}
                        onChange={(e) => { setSearch(e.target.value); setOpen(true); }}
                        onFocus={() => setOpen(true)}
                        placeholder="Search campaigns by name…"
                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                        autoComplete="off"
                    />

                    {/* Campaign list */}
                    {open && (
                        <div className="max-h-52 overflow-y-auto rounded-md border border-border bg-card shadow-sm">
                            {filtered.length === 0 ? (
                                <p className="px-3 py-2 text-xs text-content-muted">No campaigns found.</p>
                            ) : (
                                filtered.map((c) => (
                                    <button
                                        key={c.campaign_id}
                                        onClick={() => handleSelect(c)}
                                        className="flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-muted border-b border-border last:border-0"
                                    >
                                        <span className="text-sm text-content leading-tight">{c.name}</span>
                                        <span className="text-[10px] text-content-muted">
                                            ID: {c.campaign_id} · {labelFor(c.type)}
                                        </span>
                                    </button>
                                ))
                            )}
                        </div>
                    )}

                    {/* Count hint */}
                    {open && (
                        <p className="text-[10px] text-content-muted">
                            {filtered.length} of {campaigns.length} campaigns
                            {search && ` matching "${search}"`}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
};
