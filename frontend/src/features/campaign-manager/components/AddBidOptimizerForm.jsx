import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { Loading } from "../../../components/feedback/Loading";
import { useAddBidOptimizerRule, useCampaignKeywords, useCampaignProducts } from "../hooks";
import { CampaignSelector } from "./CampaignSelector";
import { api } from "../../../lib/axios";

const empty = () => ({
    campaign_id: "",
    campaign_name: "",
    lat: "",
    lon: "",
    location_name: "",
    brand_name: "",
    keyword: "",
    match_type: "EXACT",
    target_position: "",
    min_bid: "",
    max_bid: "",
    start_time: "",
    stop_time: "",
    start_date: "",
    stop_date: "",
});

const posLabel = (pos) => {
    if (pos == null) return "not ranked";
    return `#${pos}`;
};

const useBlinkitZones = () =>
    useQuery({
        queryKey: ["blinkit-zones"],
        queryFn: () => api.get("/reference/blinkit-zones"),
        staleTime: Infinity,
    });

export const AddBidOptimizerForm = ({ triggerOpen = false, onTriggerConsumed } = {}) => {
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState(empty());
    const { mutate: addRule, isPending } = useAddBidOptimizerRule();

    useEffect(() => {
        if (triggerOpen) {
            setOpen(true);
            onTriggerConsumed?.();
        }
    }, [triggerOpen]);
    const { data: zones = [], isLoading: zonesLoading } = useBlinkitZones();

    const campaignId = form.campaign_id ? parseInt(form.campaign_id) : null;
    const { data: keywords = [], isLoading: kwLoading } = useCampaignKeywords(campaignId);
    const { data: products = [], isLoading: prodLoading } = useCampaignProducts(campaignId);

    const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

    const selectKeyword = (kw) => {
        setForm((f) => ({
            ...f,
            keyword: kw.keyword,
            match_type: kw.match_type || "EXACT",
            min_bid: kw.current_cpm ? String(kw.current_cpm) : f.min_bid,
        }));
    };

    // Deduplicate zones to one entry per city
    const cities = zones.reduce((acc, z) => {
        const city = z.city || z.label;
        if (!acc.find((c) => c.city === city)) acc.push({ city, lat: z.lat, lon: z.lon });
        return acc;
    }, []);

    const selectZone = (e) => {
        const city = e.target.value;
        const zone = cities.find((c) => c.city === city);
        if (zone) {
            setForm((f) => ({
                ...f,
                location_name: zone.city,
                lat: zone.lat,
                lon: zone.lon,
            }));
        } else {
            setForm((f) => ({ ...f, location_name: "", lat: "", lon: "" }));
        }
    };

    const reset = () => { setForm(empty()); setOpen(false); };

    const canSubmit =
        form.campaign_id &&
        form.keyword.trim() &&
        form.target_position &&
        form.max_bid &&
        (!form.min_bid || parseInt(form.min_bid) <= parseInt(form.max_bid));

    const submit = () => {
        if (!canSubmit) return;
        addRule(
            {
                campaign_id: parseInt(form.campaign_id),
                campaign_name: form.campaign_name || `Campaign ${form.campaign_id}`,
                lat: form.lat ? parseFloat(form.lat) : null,
                lon: form.lon ? parseFloat(form.lon) : null,
                location_name: form.location_name || null,
                brand_name: form.brand_name.trim().toLowerCase() || null,
                keyword: form.keyword.trim().toLowerCase(),
                match_type: form.match_type,
                target_position: parseInt(form.target_position),
                min_bid: form.min_bid ? parseInt(form.min_bid) : null,
                max_bid: parseInt(form.max_bid),
                start_time: form.start_time || null,
                stop_time: form.stop_time || null,
                start_date: form.start_date || null,
                stop_date: form.stop_date || null,
            },
            { onSuccess: reset },
        );
    };

    if (!open) return null;

    return (
        <Card>
            <div className="flex flex-col gap-4">
                    {/* Campaign */}
                    <CampaignSelector
                        value={form.campaign_id}
                        onChange={(id, name) => {
                            setForm((f) => ({ ...f, campaign_id: id, campaign_name: name, keyword: "", match_type: "EXACT" }));
                        }}
                        onReset={() => setForm((f) => ({ ...f, campaign_id: "", campaign_name: "", keyword: "", match_type: "EXACT" }))}
                    />

                    {/* Dark Store Zone */}
                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">
                            City
                            <span className="ml-1 font-normal text-content-muted">(city where position will be tracked)</span>
                        </label>
                        {zonesLoading ? (
                            <Loading label="Loading zones…" />
                        ) : (
                            <select
                                value={form.location_name}
                                onChange={selectZone}
                                className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                            >
                                <option value="">— select a city (optional) —</option>
                                {cities.map((c) => (
                                    <option key={c.city} value={c.city}>{c.city}</option>
                                ))}
                            </select>
                        )}
                        {form.lat && (
                            <p className="text-[10px] text-content-muted">
                                lat={form.lat} lon={form.lon}
                            </p>
                        )}
                    </div>

                    {/* Brand Name */}
                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">
                            Brand Name
                            <span className="ml-1 font-normal text-warning">(required — used to identify your product in blinkit search)</span>
                        </label>
                        <input
                            type="text"
                            value={form.brand_name}
                            onChange={(e) => set("brand_name", e.target.value)}
                            placeholder="e.g. dobra"
                            className="rounded-md border border-warning/50 bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-warning"
                        />
                        <p className="text-[10px] text-content-muted">
                            The scraper searches for this brand in blinkit results to find your product's Ad position
                        </p>
                    </div>

                    {/* Keywords from campaign */}
                    {campaignId && (
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-content-muted">Campaign Keywords</label>
                            {kwLoading ? (
                                <Loading label="Loading keywords…" />
                            ) : keywords.length === 0 ? (
                                <p className="text-xs text-content-muted italic">No keywords found in this campaign.</p>
                            ) : (
                                <select
                                    value={form.keyword ? `${form.keyword}|${form.match_type}` : ""}
                                    onChange={(e) => {
                                        if (!e.target.value) return;
                                        const [kw, mt] = e.target.value.split("|");
                                        const found = keywords.find((k) => k.keyword === kw && k.match_type === mt);
                                        if (found) selectKeyword(found);
                                    }}
                                    className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                >
                                    <option value="">— select a keyword —</option>
                                    {keywords.map((kw) => (
                                        <option key={`${kw.keyword}-${kw.match_type}`} value={`${kw.keyword}|${kw.match_type}`}>
                                            {kw.keyword} · {kw.match_type} · ₹{kw.current_cpm?.toLocaleString() ?? "—"} CPM · pos {posLabel(kw.position)}
                                        </option>
                                    ))}
                                </select>
                            )}
                        </div>
                    )}

                    {/* Keyword input + match type — always visible, pre-filled when clicking a keyword card */}
                    <div className="grid grid-cols-2 gap-3">
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-content-muted">
                                Keyword
                                <span className="ml-1 font-normal text-content-muted">(click above or type your own)</span>
                            </label>
                            <input
                                type="text"
                                value={form.keyword}
                                onChange={(e) => set("keyword", e.target.value)}
                                placeholder="e.g. soda"
                                className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-content-muted">Match Type</label>
                            <select
                                value={form.match_type}
                                onChange={(e) => set("match_type", e.target.value)}
                                className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                            >
                                <option value="EXACT">Exact</option>
                                <option value="SMART">Smart (Broad)</option>
                            </select>
                        </div>
                    </div>

                    {/* Products in campaign */}
                    {campaignId && (
                        <div className="flex flex-col gap-1.5">
                            <label className="text-xs font-medium text-content-muted">Products in this Campaign</label>
                            {prodLoading ? (
                                <Loading label="Loading products…" />
                            ) : products.length === 0 ? (
                                <p className="text-xs text-content-muted italic">No products found.</p>
                            ) : (
                                <div className="flex flex-wrap gap-1.5">
                                    {products.map((p) => (
                                        <span
                                            key={p.pid}
                                            className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-content-muted"
                                        >
                                            {p.pid} — {p.name}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Bid params — always shown once campaign is selected */}
                    {campaignId && (
                        <>
                            {/* Target / Min / Max */}
                            <div className="grid grid-cols-3 gap-3">
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-content-muted">Target Position</label>
                                    <input
                                        type="number"
                                        min="1"
                                        value={form.target_position}
                                        onChange={(e) => set("target_position", e.target.value)}
                                        placeholder="e.g. 5"
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-content-muted">Min Bid ₹ <span className="font-normal text-content-muted">(optional — auto from Blinkit)</span></label>
                                    <input
                                        type="number"
                                        min="1"
                                        value={form.min_bid}
                                        onChange={(e) => set("min_bid", e.target.value)}
                                        placeholder="Auto (fetched from Blinkit)"
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-content-muted">Max Bid ₹</label>
                                    <input
                                        type="number"
                                        min="1"
                                        value={form.max_bid}
                                        onChange={(e) => set("max_bid", e.target.value)}
                                        placeholder="e.g. 2000"
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                            </div>

                            {/* Date range */}
                            <div className="grid grid-cols-2 gap-3">
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-content-muted">Start Date (optional)</label>
                                    <input
                                        type="date"
                                        value={form.start_date}
                                        onChange={(e) => set("start_date", e.target.value)}
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-content-muted">Stop Date (optional)</label>
                                    <input
                                        type="date"
                                        value={form.stop_date}
                                        onChange={(e) => set("stop_date", e.target.value)}
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                            </div>

                            {/* Time range */}
                            <div className="grid grid-cols-2 gap-3">
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-content-muted">Start Time IST (optional)</label>
                                    <input
                                        type="time"
                                        value={form.start_time}
                                        onChange={(e) => set("start_time", e.target.value)}
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-content-muted">Stop Time IST (optional)</label>
                                    <input
                                        type="time"
                                        value={form.stop_time}
                                        onChange={(e) => set("stop_time", e.target.value)}
                                        className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                                    />
                                </div>
                            </div>

                            {form.min_bid && form.max_bid && parseInt(form.min_bid) > parseInt(form.max_bid) && (
                                <p className="text-xs text-danger">Min bid cannot exceed max bid.</p>
                            )}

                            <div className="flex gap-2 pt-1">
                                <Button onClick={submit} disabled={isPending || !canSubmit}>
                                    {isPending ? "Saving…" : "Save Rule"}
                                </Button>
                                <Button variant="secondary" onClick={reset}>Cancel</Button>
                            </div>
                        </>
                    )}

                    {/* Cancel when no campaign selected yet */}
                    {!campaignId && (
                        <div className="flex gap-2 pt-1">
                            <Button variant="secondary" onClick={reset}>Cancel</Button>
                        </div>
                    )}
            </div>
        </Card>
    );

};



