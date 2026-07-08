import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { useLivePositions } from "../hooks";
import { api } from "../../../lib/axios";

const useBlinkitZones = () =>
    useQuery({
        queryKey: ["blinkit-zones"],
        queryFn: () => api.get("/reference/blinkit-zones"),
        staleTime: Infinity,
    });

export const LivePositionCheck = ({ brandName = "dobra" }) => {
    const [keyword, setKeyword] = useState("");
    const [selectedZone, setSelectedZone] = useState(null);
    const [brand, setBrand] = useState(brandName);

    const { data: zones = [] } = useBlinkitZones();
    const { mutate: check, isPending, isError, error, data: results } = useLivePositions();

    const positions = results ?? [];

    const handleCheck = () => {
        if (!keyword.trim()) return;
        const lat = selectedZone?.lat ?? 12.9767;
        const lon = selectedZone?.lon ?? 77.5713;
        check({ keyword: keyword.trim().toLowerCase(), lat, lon });
    };

    const isOwnBrand = (item) => {
        const b = brand.trim().toLowerCase();
        return b && (
            item.name.toLowerCase().includes(b) ||
            item.is_ad
        ) && item.name.toLowerCase().includes(b);
    };

    const ownItems = positions.filter(isOwnBrand);

    return (
        <Card title="Live Position Check">
            <div className="flex flex-col gap-3">
                <p className="text-xs text-content-muted">
                    Scrapes blinkit.com in real-time to show where your products appear for a keyword.
                </p>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">Keyword</label>
                        <input
                            type="text"
                            value={keyword}
                            onChange={(e) => setKeyword(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && handleCheck()}
                            placeholder="e.g. soda, sprite"
                            className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                        />
                    </div>

                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">Location</label>
                        <select
                            onChange={(e) => {
                                const z = zones.find((z) => z.label === e.target.value);
                                setSelectedZone(z || null);
                            }}
                            className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                        >
                            <option value="">— Bengaluru (default) —</option>
                            {zones.map((z) => (
                                <option key={z.label} value={z.label}>{z.label}</option>
                            ))}
                        </select>
                    </div>

                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-content-muted">Your Brand</label>
                        <input
                            type="text"
                            value={brand}
                            onChange={(e) => setBrand(e.target.value)}
                            placeholder="e.g. dobra"
                            className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-content outline-none focus:border-primary"
                        />
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                    <Button onClick={handleCheck} disabled={isPending || !keyword.trim()}>
                        {isPending ? "Scraping blinkit.com… (~20s)" : "Check Live Position"}
                    </Button>
                    {isError && (
                        <span className="text-xs text-danger">
                            {error?.message ?? "Failed to fetch live positions."}
                        </span>
                    )}
                    {!isPending && results !== undefined && positions.length === 0 && (
                        <span className="text-xs text-content-muted italic">No results returned — try a different keyword or location.</span>
                    )}
                    {ownItems.length > 0 && (
                        <span className="text-xs text-success font-medium">
                            Your brand found at position{ownItems.length > 1 ? "s" : ""}{" "}
                            {ownItems.map((i) => `#${i.position}`).join(", ")}
                        </span>
                    )}
                    {positions.length > 0 && ownItems.length === 0 && (
                        <span className="text-xs text-warning font-medium">
                            Your brand not found in {positions.length} results
                        </span>
                    )}
                </div>

                {positions.length > 0 && (
                    <div className="overflow-x-auto rounded-md border border-border">
                        <table className="w-full text-xs">
                            <thead>
                                <tr className="border-b border-border bg-muted text-left text-content-muted">
                                    <th className="px-3 py-2 font-medium">#</th>
                                    <th className="px-3 py-2 font-medium">Product</th>
                                    <th className="px-3 py-2 font-medium">Type</th>
                                    <th className="px-3 py-2 font-medium">PID</th>
                                </tr>
                            </thead>
                            <tbody>
                                {positions.map((item) => {
                                    const own = isOwnBrand(item);
                                    return (
                                        <tr
                                            key={item.position}
                                            className={`border-b border-border/50 last:border-0 ${own ? "bg-success/10" : ""}`}
                                        >
                                            <td className={`px-3 py-2 font-semibold ${own ? "text-success" : "text-content-muted"}`}>
                                                #{item.position}
                                            </td>
                                            <td className={`px-3 py-2 ${own ? "font-semibold text-success" : "text-content"}`}>
                                                {item.name}
                                                {own && <span className="ml-2 text-[10px] bg-success/20 text-success px-1.5 py-0.5 rounded-full">YOUR BRAND</span>}
                                            </td>
                                            <td className="px-3 py-2">
                                                {item.is_ad
                                                    ? <span className="text-warning font-medium">Ad</span>
                                                    : <span className="text-content-muted">Organic</span>
                                                }
                                            </td>
                                            <td className="px-3 py-2 text-content-muted font-mono">
                                                {item.pid || "—"}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </Card>
    );
};
