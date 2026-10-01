import { useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Drawer } from "../../../components/ui/Drawer";
import { formatCurrency, formatNumber } from "../../../lib/format";

/**
 * The rows behind an attention item, in a side panel: which SKUs, which
 * campaigns, which keywords.
 *
 * Tabs re-sort rather than filter, so the row count never changes under the
 * reader. Rows with no ratio show a dash rather than a zero — "not matched to
 * the public scrape" and "out of stock nowhere" are different facts.
 */
const FIRST_PAGE = 6;

const KIND = {
	availability: "Inventory issue",
	fill_loss: "Supply issue",
	inefficient_spend: "Marketing issue",
	visibility: "Visibility change",
	pricing: "Pricing opportunity",
};

const showValue = (value, unit) => {
	if (value === null || value === undefined) return "—";
	if (unit === "INR") return formatCurrency(value);
	if (unit === "percent") return `${value}%`;
	if (unit === "percentage_points")
		return `${value > 0 ? "+" : ""}${value}pp`;
	return formatNumber(value);
};

const Ratio = ({ count, total }) =>
	total ? (
		<>
			<span className="font-semibold text-content">
				{formatNumber(count ?? 0)}
			</span>
			<span className="text-content-subtle">
				{" / "}
				{formatNumber(total)}
			</span>
		</>
	) : (
		// A dash, not a zero: "not matched to the public scrape" and "out of
		// stock nowhere" are different facts.
		<span className="text-content-subtle">—</span>
	);

const Row = ({ item, ratioMode, secondary }) => (
	<li className="flex items-center gap-3 border-b border-border py-3 last:border-0">
		<span className="min-w-0 flex-1">
			<span className="block truncate text-sm font-medium text-content">
				{item.label}
			</span>
		</span>

		<span className="w-20 shrink-0 text-right text-sm tabular-nums">
			{ratioMode ? (
				<Ratio count={item.count} total={item.total} />
			) : (
				<span className="font-semibold text-content">
					{showValue(item.value, item.unit)}
				</span>
			)}
		</span>

		{secondary && (
			<span className="w-14 shrink-0 text-right text-sm tabular-nums">
				<Ratio
					count={item.secondary_count}
					total={item.secondary_total}
				/>
			</span>
		)}
	</li>
);

export const InsightPanel = ({ insight, onClose }) => {
	const [showAll, setShowAll] = useState(false);

	const items = insight?.items ?? [];
	const ratioMode = items.some((i) => i.total != null);

	const rows = useMemo(() => {
		const metric = (i) => (ratioMode ? (i.count ?? -1) : (i.value ?? -1));
		return [...items].sort((a, b) => metric(b) - metric(a));
	}, [items, ratioMode]);

	if (!insight) return null;

	const visible = showAll ? rows : rows.slice(0, FIRST_PAGE);
	const secondary = items.some((i) => i.secondary_total != null);

	return (
		<Drawer
			open={Boolean(insight)}
			onClose={onClose}
			title={
				<span className="flex flex-col gap-1.5">
					<span className="flex items-center gap-2">
						<span
							aria-hidden
							className="h-2 w-2 rounded-full bg-danger"
						/>
						<span className="text-[11px] font-semibold tracking-[0.1em] text-danger uppercase">
							{KIND[insight.impact?.type] ?? "Needs attention"}
						</span>
					</span>
					<span className="font-display text-xl font-bold text-content">
						{insight.title}
					</span>
				</span>
			}
			subtitle={insight.as_of}
		>
			<div className="flex flex-col gap-5">
				<p className="text-sm leading-relaxed text-content-muted">
					{insight.what}
				</p>

				{items.length > 0 && (
					<>
						{/* Column headers — the two things each row is about. */}
						<div className="flex items-center gap-3 border-b border-border pb-1.5 text-[11px] tracking-wide text-content-subtle uppercase">
							<span className="min-w-0 flex-1">SKU</span>
							<span className="w-20 shrink-0 text-right">
								{insight.item_label ?? "Value"}
							</span>
							{secondary && (
								<span className="w-14 shrink-0 text-right">
									{insight.item_secondary_label ?? ""}
								</span>
							)}
						</div>

						<ul className="flex flex-col">
							{visible.map((item, i) => (
								<Row
									key={`${item.label}-${i}`}
									item={item}
									ratioMode={ratioMode}
									secondary={secondary}
								/>
							))}
						</ul>

						{rows.length > FIRST_PAGE && (
							<div className="flex items-center justify-between gap-3">
								<span className="text-xs text-content-muted">
									Showing {visible.length} of {rows.length}
								</span>
								<button
									type="button"
									onClick={() => setShowAll((was) => !was)}
									className="text-xs font-medium text-brand hover:underline"
								>
									{showAll
										? "Show fewer"
										: `View all ${rows.length}`}
								</button>
							</div>
						)}
					</>
				)}

				{/* The panel lists what is affected; the full record lives on the
				    page the insight came from. */}
				<Link
					to={insight.href}
					onClick={onClose}
					className="inline-flex items-center gap-1.5 self-start border-t border-border pt-4 text-sm font-medium text-brand hover:underline"
				>
					{insight.cta}
					<ArrowRight size={14} aria-hidden />
				</Link>
			</div>
		</Drawer>
	);
};
