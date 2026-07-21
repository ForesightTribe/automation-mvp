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
 * Two-step campaign selector: Category → Campaign.
 * Props:
 *   value        – selected campaign_id (string)
 *   onChange     – (campaign_id: string, campaign_name: string) => void
 *   onReset      – called when category changes (optional)
 */
export const CampaignSelector = ({ value, onChange, onReset }) => {
    const { data: campaignsPage } = useCampaigns();
    const campaigns = campaignsPage?.items ?? [];

    const [category, setCategory] = useState("");

    // Derive sorted unique categories from loaded campaigns
    const categories = [...new Set(campaigns.map((c) => c.type).filter(Boolean))].sort();

    const filtered = category
        ? campaigns.filter((c) => c.type === category)
        : campaigns;

    const handleCategoryChange = (e) => {
        setCategory(e.target.value);
        onChange("", "");
        onReset?.();
    };

    const handleCampaignChange = (e) => {
        const selected = filtered.find((c) => String(c.campaign_id) === e.target.value);
        onChange(e.target.value, selected?.name ?? "");
    };

    // If value is cleared externally, reset category too
    useEffect(() => {
        if (!value) setCategory("");
    }, [value]);

    return (
        <div className="flex flex-col gap-3">
            {/* Category */}
            <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-content-muted">Campaign Category</label>
                <select
                    value={category}
                    onChange={handleCategoryChange}
                    className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                >
                    <option value="">— All categories —</option>
                    {categories.map((t) => (
                        <option key={t} value={t}>
                            {labelFor(t)}
                        </option>
                    ))}
                </select>
            </div>

            {/* Campaign */}
            <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-content-muted">Campaign</label>
                <select
                    value={value}
                    onChange={handleCampaignChange}
                    className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                >
                    <option value="">— Select a campaign —</option>
                    {filtered.map((c) => (
                        <option key={c.campaign_id} value={c.campaign_id}>
                            {c.name} ({c.campaign_id})
                        </option>
                    ))}
                </select>
                {category && filtered.length === 0 && (
                    <p className="text-xs text-content-muted">No campaigns found for this category.</p>
                )}
            </div>
        </div>
    );
};



