import { useTopSkus, usePreviousTopSkus } from "../hooks";
import { Loading } from "../../../components/feedback/Loading";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency } from "../../../lib/format";

/**
 * Every SKU by what it is worth and which way it is going.
 *
 * Size and direction together separate the SKU carrying the business from the
 * one carrying its growth. Share of revenue sits on the row because the same
 * percentage fall means different things at 1% and 30% of the business.
 *
 * ⚠️ A fall is reported, never judged — a deliberate wind-down and a supply
 * problem look identical here. Nothing is coloured as a risk.
 */
const SHOWN = 12;

export const ProductMatrix = () => {
	const { data: now, isLoading } = useTopSkus(50);
	const { data: before } = usePreviousTopSkus(50);

	const prior = new Map(
		(before ?? []).map((r) => [r.item_name ?? r.item_id, r.revenue]),
	);
	const total = (now ?? []).reduce((s, r) => s + (r.revenue ?? 0), 0);

	const rows = (now ?? [])
		.map((r) => {
			const name = r.item_name ?? r.item_id;
			const was = prior.get(name) ?? 0;
			return {
				name,
				revenue: r.revenue,
				share: total ? (r.revenue / total) * 100 : 0,
				change: r.revenue - was,
				pct: was ? ((r.revenue - was) / was) * 100 : null,
			};
		})
		.sort((a, b) => b.revenue - a.revenue)
		.slice(0, SHOWN);

	return (
		<section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
			<div className="flex flex-col gap-0.5">
				<h2 className="font-display text-base font-semibold text-content">
					Product performance
				</h2>
				<p className="text-xs text-content-muted">
					What each SKU is worth, and which way it moved against the
					previous period.
				</p>
			</div>

			{isLoading && <Loading label="Loading products…" />}
			{!isLoading && rows.length === 0 && (
				<EmptyState message="No SKUs in this period." />
			)}

			{rows.length > 0 && (
				<>
					<div className="flex items-baseline gap-3 border-b border-border pb-1.5 text-[11px] tracking-wide text-content-subtle uppercase">
						<span className="flex-1 pl-2">SKU</span>
						<span className="w-28 text-right">Revenue</span>
						<span className="w-24 text-right">Share</span>
						<span className="w-28 text-right">Change</span>
						<span className="w-16 text-right">%</span>
					</div>
					<ul className="flex flex-col">
						{rows.map((r) => (
							<li
								key={r.name}
								className="flex items-baseline gap-3 border-b border-border py-2 last:border-0"
							>
								<span
									title={r.name}
									className="min-w-0 flex-1 truncate pl-2 text-sm text-content"
								>
									{r.name}
								</span>
								<span className="w-28 text-right text-sm font-medium text-content tabular-nums">
									{formatCurrency(r.revenue)}
								</span>
								{/* Share carries a bar because the spread here is
								    the point: one SKU is a third of the business. */}
								<span className="flex w-24 shrink-0 items-center gap-2">
									<span
										aria-hidden
										className="relative block h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
									>
										<span
											className="absolute inset-y-0 left-0 rounded-full bg-info"
											style={{
												width: `${Math.max(2, r.share)}%`,
											}}
										/>
									</span>
									<span className="w-8 shrink-0 text-right text-[11px] text-content-muted tabular-nums">
										{r.share.toFixed(0)}%
									</span>
								</span>
								<span className="w-28 text-right text-sm text-content-muted tabular-nums">
									{r.change >= 0 ? "+" : "−"}
									{formatCurrency(Math.abs(r.change))}
								</span>
								<span className="w-16 text-right text-[11px] text-content-muted tabular-nums">
									{r.pct == null
										? "new"
										: `${r.pct >= 0 ? "▲" : "▼"} ${Math.abs(r.pct).toFixed(0)}%`}
								</span>
							</li>
						))}
					</ul>
				</>
			)}
		</section>
	);
};
