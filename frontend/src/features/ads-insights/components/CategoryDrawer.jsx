import { useMemo } from "react";
import { Drawer } from "../../../components/ui/Drawer";
import { EChart } from "../../../components/charts/EChart";
import { Loading } from "../../../components/feedback/Loading";
import { miniCompareOption, SERIES } from "../chartOptions";
import { useCategoryTrend, useCityCategory } from "../../analytics/hooks";
import { formatCurrency, formatNumber } from "../../../lib/format";

const dash = "—";

const Section = ({ title, hint, children }) => (
	<section className="mb-6 last:mb-0">
		<div className="mb-2 flex items-baseline justify-between gap-3">
			<h3 className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
				{title}
			</h3>
			{hint && (
				<span className="text-[11px] text-content-subtle">{hint}</span>
			)}
		</div>
		{children}
	</section>
);

const Stat = ({ label, value }) => (
	<div className="bg-card px-4 py-3">
		<p className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
			{label}
		</p>
		<p className="mt-1 font-display text-lg font-semibold text-content tabular-nums">
			{value}
		</p>
	</div>
);

/**
 * One category in full, opened from the table.
 *
 * ⚠️ Everything here is SALES data, not ad-attributed revenue, because Blinkit publishes no
 * category dimension on ad performance. The badge on the card says so and the subtitle
 * repeats it, since a drawer opened from an ads page is exactly where someone would assume
 * otherwise.
 *
 * The two breakdowns answer the questions the row itself cannot: whether the category is
 * growing or shrinking across the window, and whether its revenue is one city or many.
 */
export const CategoryDrawer = ({ row, range, open, onClose }) => {
	const category = row?.category;
	const { data: trend, isLoading: loadingTrend } = useCategoryTrend();
	const { data: cells, isLoading: loadingCities } = useCityCategory();

	const daily = useMemo(
		() =>
			(trend ?? [])
				.filter((r) => r.category === category)
				.sort((a, b) => a.date.localeCompare(b.date)),
		[trend, category],
	);

	const cities = useMemo(
		() =>
			(cells ?? [])
				.filter((c) => c.category === category)
				.sort((a, b) => (b.revenue ?? 0) - (a.revenue ?? 0))
				.slice(0, 10),
		[cells, category],
	);

	if (!open || !row) return null;

	const cityTotal = cities.reduce((s, c) => s + (c.revenue ?? 0), 0);
	const best = daily.reduce(
		(m, d) => (m == null || (d.revenue ?? 0) > (m.revenue ?? 0) ? d : m),
		null,
	);

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={category}
			subtitle={`Sales data${range ? ` · ${range.from} to ${range.to}` : ""}`}
			stats={
				<>
					<Stat
						label="Revenue"
						value={formatCurrency(row.revenue ?? 0)}
					/>
					<Stat
						label="Units"
						value={formatNumber(row.units_sold ?? 0)}
					/>
					<Stat
						label="Share of revenue"
						value={
							row.share == null
								? dash
								: `${row.share.toFixed(1)}%`
						}
					/>
				</>
			}
		>
			<Section title="Performance">
				<dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
					{[
						[
							"Revenue per unit",
							row.aov == null ? dash : formatCurrency(row.aov),
						],
						[
							"Days with sales",
							daily.length ? formatNumber(daily.length) : dash,
						],
						[
							"Best day",
							best
								? `${best.date} · ${formatCurrency(best.revenue ?? 0)}`
								: dash,
						],
						[
							"Cities selling it",
							cities.length ? formatNumber(cities.length) : dash,
						],
					].map(([k, v]) => (
						<div
							key={k}
							className="flex justify-between gap-3 border-b border-border/60 py-1"
						>
							<dt className="text-content-muted">{k}</dt>
							<dd className="tabular-nums text-content">{v}</dd>
						</div>
					))}
				</dl>
			</Section>

			<Section
				title="Revenue over the window"
				hint={daily.length ? `${daily.length} days` : ""}
			>
				{loadingTrend ? (
					<Loading label="Loading trend…" />
				) : daily.length === 0 ? (
					<p className="text-sm text-content-muted">
						No daily rows for this category in this window.
					</p>
				) : (
					<EChart
						option={miniCompareOption(
							daily.map((d) => d.revenue ?? 0),
							[],
							{ color: SERIES[0], format: formatCurrency },
						)}
						height={120}
					/>
				)}
			</Section>

			<Section
				title="Top cities"
				hint={
					cityTotal
						? `${formatCurrency(cityTotal)} of ${formatCurrency(row.revenue ?? 0)}`
						: ""
				}
			>
				{loadingCities ? (
					<Loading label="Loading cities…" />
				) : cities.length === 0 ? (
					<p className="text-sm text-content-muted">
						No city breakdown for this category in this window.
					</p>
				) : (
					<table className="w-full text-sm">
						<tbody>
							{cities.map((c) => (
								<tr
									key={c.city}
									className="border-b border-border/60 last:border-0"
								>
									<td className="py-1.5 pr-2 text-content">
										{c.city}
									</td>
									<td className="py-1.5 text-right tabular-nums text-content-muted">
										{formatNumber(c.units_sold ?? 0)}
									</td>
									<td className="py-1.5 text-right tabular-nums text-content">
										{formatCurrency(c.revenue ?? 0)}
									</td>
								</tr>
							))}
						</tbody>
					</table>
				)}
			</Section>
		</Drawer>
	);
};
