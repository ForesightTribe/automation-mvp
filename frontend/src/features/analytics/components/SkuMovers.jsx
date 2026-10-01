import { useTopSkus, usePreviousTopSkus } from "../hooks";
import { Loading } from "../../../components/feedback/Loading";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency } from "../../../lib/format";

/**
 * What moved between this window and the one before it, by rupees.
 *
 * The rest of this page ranks by size; this ranks by direction.
 *
 * ⚠️ A fall is reported, never judged — a deliberate wind-down and a supply
 * problem look identical here. No red, no green, no "risk" wording.
 *
 * Ranked by absolute rupees: a tail SKU doubling is a big percentage and small
 * news.
 */
const ROWS = 5;

const Row = ({ row }) => {
	const up = row.change > 0;
	return (
		<li className="flex items-baseline gap-3 border-b border-border py-2 last:border-0">
			<span
				title={row.name}
				className="min-w-0 flex-1 truncate text-sm text-content"
			>
				{row.name}
			</span>
			<span className="w-24 text-right text-sm font-medium text-content tabular-nums">
				{up ? "+" : "−"}
				{formatCurrency(Math.abs(row.change))}
			</span>
			<span className="w-16 text-right text-[11px] text-content-muted tabular-nums">
				{row.pct == null
					? "new"
					: `${up ? "▲" : "▼"} ${Math.abs(row.pct).toFixed(0)}%`}
			</span>
		</li>
	);
};

const Column = ({ title, rows }) => (
	<div className="flex flex-col gap-1.5">
		<p className="text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
			{title}
		</p>
		{rows.length === 0 ? (
			<p className="py-1 text-xs text-content-subtle">No change</p>
		) : (
			<ul className="flex flex-col">
				{rows.map((r) => (
					<Row key={r.name} row={r} />
				))}
			</ul>
		)}
	</div>
);

export const SkuMovers = () => {
	const { data: now, isLoading } = useTopSkus(50);
	const { data: before } = usePreviousTopSkus(50);

	const prior = new Map(
		(before ?? []).map((r) => [r.item_name ?? r.item_id, r.revenue]),
	);
	const seen = new Set();
	const moved = [];

	for (const r of now ?? []) {
		const name = r.item_name ?? r.item_id;
		seen.add(name);
		const was = prior.get(name) ?? 0;
		moved.push({
			name,
			change: r.revenue - was,
			// A SKU with nothing behind it has no percentage — it is new, which
			// is a different fact from "up a lot".
			pct: was ? ((r.revenue - was) / was) * 100 : null,
		});
	}
	// SKUs that sold before and not at all now: a real move, and the one most
	// easily lost by only walking the current window.
	for (const [name, was] of prior) {
		if (!seen.has(name) && was) {
			moved.push({ name, change: -was, pct: -100 });
		}
	}

	const gained = moved
		.filter((r) => r.change > 0)
		.sort((a, b) => b.change - a.change)
		.slice(0, ROWS);
	const fell = moved
		.filter((r) => r.change < 0)
		.sort((a, b) => a.change - b.change)
		.slice(0, ROWS);

	return (
		<section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
			<div className="flex flex-col gap-0.5">
				<h2 className="font-display text-base font-semibold text-content">
					What moved
				</h2>
				<p className="text-xs text-content-muted">
					Change in revenue against the previous period of the same
					length.
				</p>
			</div>

			{isLoading && <Loading label="Loading movers…" />}
			{!isLoading && moved.length === 0 && (
				<EmptyState message="No SKUs in this period." />
			)}

			{moved.length > 0 && (
				<div className="grid grid-cols-1 gap-x-12 gap-y-5 lg:grid-cols-2">
					<Column title="Grew most" rows={gained} />
					<Column title="Fell most" rows={fell} />
				</div>
			)}
		</section>
	);
};
