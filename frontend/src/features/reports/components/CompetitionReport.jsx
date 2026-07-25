import { useState } from "react";
import { useCompetition } from "../hooks";
import { formatCurrency, formatUnitPrice } from "../../../lib/format";
import { ViewToggle } from "../../../components/ui/ViewToggle";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";

/**
 * Competition pricing — own SKU vs competitors, grouped by marketplace + keyword,
 * normalized per unit (₹/100 ml · 100 g · piece) so different pack sizes compare
 * fairly. Sourced from `search_listings` (own + competitors surface together per
 * search). The per-unit index compares each competitor against the own reference.
 */

const KINDS = [
	{ value: "main", label: "Singles" },
	{ value: "combo", label: "Combos" },
	{ value: "all", label: "All" },
];

const IndexBadge = ({ ownPerUnit, compPerUnit }) => {
	if (!ownPerUnit || !compPerUnit)
		return <span className="text-content-subtle">—</span>;
	const diff = (ownPerUnit - compPerUnit) / compPerUnit;
	const cheaper = diff < 0;
	return (
		<span
			className={`rounded px-1.5 py-0.5 text-xs font-medium ${
				cheaper
					? "bg-success-soft text-success"
					: "bg-danger-soft text-danger"
			}`}
		>
			{diff > 0 ? "+" : ""}
			{(diff * 100).toFixed(0)}% vs comp
		</span>
	);
};

/** "675 ml ×3" / "225 ml" — pack size, unit, and count (count omitted when 1). */
const packLabel = (row) => {
	if (row.pack_size == null || !row.pack_uom) return "—";
	const base = `${row.pack_size} ${row.pack_uom}`;
	return row.pack_count > 1 ? `${base} ×${row.pack_count}` : base;
};

export const CompetitionReport = () => {
	const [kind, setKind] = useState("main");
	const { data, isLoading, error, refetch } = useCompetition(kind);

	return (
		<div className="flex flex-col gap-4">
			<div className="flex justify-end">
				<ViewToggle options={KINDS} value={kind} onChange={setKind} />
			</div>

			{isLoading && <Loading label="Loading competition report…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading && !error && data && !data.groups.length && (
				<div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-content-muted">
					No competitor pricing in the selected window.
				</div>
			)}
			{!isLoading && !error && data && (
				<div className="flex flex-col gap-6">
					{data.groups.map((group) => (
						<CompGroup
							key={`${group.marketplace}-${group.keyword}`}
							group={group}
						/>
					))}
				</div>
			)}
		</div>
	);
};

const CompGroup = ({ group }) => {
	// Own reference per-unit price — the first own SKU that has one (usually the only).
	const ownPerUnit = group.own.find((o) => o.unit_price)?.unit_price ?? null;

	return (
		<div className="overflow-x-auto rounded-xl border border-border bg-card">
			<div className="flex items-center gap-2 border-b border-border bg-muted/60 px-4 py-2">
				<span className="font-display text-sm font-semibold text-content capitalize">
					{group.marketplace}
				</span>
				<span className="text-sm text-content-muted">
					· {group.keyword}
				</span>
			</div>
			<table className="w-full border-collapse text-sm">
				<thead>
					<tr className="border-b border-border text-content-subtle">
						<th className="px-3 py-2 text-left font-medium">
							Brand / Product
						</th>
						<th className="px-3 py-2 text-right font-medium">
							MRP
						</th>
						<th className="px-3 py-2 text-right font-medium">SP</th>
						<th className="px-3 py-2 text-right font-medium">
							Pack
						</th>
						<th className="px-3 py-2 text-right font-medium">
							Per unit
						</th>
						<th className="px-3 py-2 text-right font-medium">
							Index
						</th>
					</tr>
				</thead>
				<tbody>
					{group.own.map((row) => (
						<PriceRow key={`own-${row.name}`} row={row} own />
					))}
					{group.competitors.map((row) => (
						<PriceRow
							key={`comp-${row.name}`}
							row={row}
							ownPerUnit={ownPerUnit}
						/>
					))}
				</tbody>
			</table>
		</div>
	);
};

const PriceRow = ({ row, own = false, ownPerUnit }) => {
	return (
		<tr
			className={`border-b border-border/60 last:border-0 ${
				own ? "bg-primary-soft/50 font-medium" : "hover:bg-muted/40"
			}`}
		>
			<td className="max-w-70 truncate px-3 py-1.5 text-left text-content">
				{own ? "★ " : ""}
				{row.name}
			</td>
			<td className="px-3 py-1.5 text-right tabular-nums text-content-muted">
				{row.mrp === null ? "—" : formatCurrency(row.mrp)}
			</td>
			<td className="px-3 py-1.5 text-right tabular-nums text-content">
				{row.sp === null ? "—" : formatCurrency(row.sp)}
			</td>
			<td className="px-3 py-1.5 text-right tabular-nums text-content-muted">
				{packLabel(row)}
			</td>
			<td className="px-3 py-1.5 text-right tabular-nums text-content-muted">
				{formatUnitPrice(row.unit_price, row.pack_uom)}
			</td>
			<td className="px-3 py-1.5 text-right">
				{own ? (
					<span className="text-xs text-content-subtle">own</span>
				) : (
					<IndexBadge
						ownPerUnit={ownPerUnit}
						compPerUnit={row.unit_price}
					/>
				)}
			</td>
		</tr>
	);
};
