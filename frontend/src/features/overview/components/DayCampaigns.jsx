import { useState } from "react";
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import { useTopCampaignsForDay } from "../hooks";
import { formatCurrency, formatNumber } from "../../../lib/format";
import { buBand } from "../../../lib/budgetBands";
import { marketplaceName } from "../../../lib/marketplace";
import { MarketplaceMark } from "../../../components/ui/MarketplaceMark";

/**
 * Every campaign that ran on the day above, with what it cost and returned.
 *
 * Reads the SAME single day as the figures above it, not the picker's window —
 * "yesterday's campaigns" and "the quarter's campaigns" are different questions
 * and should not share a heading.
 *
 * Spend, return and impressions sit beside the revenue because a figure is only
 * readable next to what was risked for it: ₹61,221 on ₹6,079 of spend and
 * ₹61,221 on ₹40,000 are the same revenue and completely different news.
 *
 * Budget use is kept as a percentage rather than the budget itself — the rupee
 * ceiling matters only as the denominator of how much of it was reached.
 */
const ROWS_SHOWN = 5;

/** RoAS and budget use are ratios the row carries rather than the API. */
const VALUE = {
	marketplace: (c) => c.marketplace ?? "",
	name: (c) => (c.name ?? String(c.campaign_id)).toLowerCase(),
	ad_sales: (c) => c.ad_sales ?? 0,
	budget_consumed: (c) => c.budget_consumed ?? 0,
	roas: (c) => (c.budget_consumed ? c.ad_sales / c.budget_consumed : -1),
	budget_used: (c) =>
		c.daily_budget && c.budget_consumed != null
			? c.budget_consumed / c.daily_budget
			: -1,
	impressions: (c) => c.impressions ?? 0,
};

const Header = ({ label, sortKey, sort, onSort, className = "" }) => {
	const active = sort.key === sortKey;
	const Icon = !active ? ChevronsUpDown : sort.asc ? ChevronUp : ChevronDown;
	return (
		<button
			type="button"
			onClick={() => onSort(sortKey)}
			className={`flex items-center gap-1 text-[11px] tracking-wide uppercase transition-colors hover:text-content ${
				active ? "text-content" : "text-content-subtle"
			} ${className}`}
		>
			{label}
			<Icon size={11} aria-hidden className="shrink-0" />
		</button>
	);
};

export const DayCampaigns = ({ day }) => {
	const { data } = useTopCampaignsForDay(day);
	const [expanded, setExpanded] = useState(false);
	const [sort, setSort] = useState({ key: "ad_sales", asc: false });

	// A first click sorts a column downward, since every measure here is one
	// where "most" is the question being asked; the name is the exception.
	const onSort = (key) =>
		setSort((s) =>
			s.key === key
				? { key, asc: !s.asc }
				: { key, asc: key === "name" || key === "marketplace" },
		);

	// Everything that RAN, not everything that earned. Banner campaigns are
	// attributed no revenue at all, so a revenue filter hides them even on days
	// they spent the most.
	const all = [...(data?.items ?? [])].filter(
		(c) => (c.budget_consumed ?? 0) > 0 || (c.impressions ?? 0) > 0,
	);
	const read = VALUE[sort.key] ?? VALUE.ad_sales;
	all.sort((a, b) => {
		const x = read(a);
		const y = read(b);
		const cmp = typeof x === "string" ? x.localeCompare(y) : x - y;
		return sort.asc ? cmp : -cmp;
	});
	const rows = expanded ? all : all.slice(0, ROWS_SHOWN);

	// The channel column earns its width only where campaigns run on more than
	// one — otherwise it repeats the same word down every row.
	const showChannel = new Set(all.map((c) => c.marketplace)).size > 1;

	if (!all.length) return null;

	return (
		<div className="flex flex-col gap-3 border-t border-border pt-5">
			<div className="flex items-baseline gap-3 border-b border-border pb-1.5">
				{showChannel && (
					<Header
						label="Channel"
						sortKey="marketplace"
						sort={sort}
						onSort={onSort}
						className="w-24"
					/>
				)}
				<Header
					label="Campaign"
					sortKey="name"
					sort={sort}
					onSort={onSort}
					className="flex-1"
				/>
				<Header
					label="Ad revenue"
					sortKey="ad_sales"
					sort={sort}
					onSort={onSort}
					className="w-24 justify-end"
				/>
				<Header
					label="Spend"
					sortKey="budget_consumed"
					sort={sort}
					onSort={onSort}
					className="w-20 justify-end"
				/>
				<Header
					label="RoAS"
					sortKey="roas"
					sort={sort}
					onSort={onSort}
					className="w-16 justify-end"
				/>
				<Header
					label="Budget used"
					sortKey="budget_used"
					sort={sort}
					onSort={onSort}
					className="w-24 justify-end"
				/>
				<Header
					label="Impressions"
					sortKey="impressions"
					sort={sort}
					onSort={onSort}
					className="w-20 justify-end"
				/>
			</div>

			<ul className="flex flex-col">
				{rows.map((c) => {
					const bu =
						c.daily_budget && c.budget_consumed != null
							? (c.budget_consumed / c.daily_budget) * 100
							: null;
					return (
						<li
							key={c.campaign_id}
							className="flex items-center gap-3 border-b border-border py-1.5 last:border-0"
						>
							{showChannel && (
								<span className="flex w-24 min-w-0 items-center gap-1.5 text-sm text-content">
									<MarketplaceMark
										marketplace={{
											slug: c.marketplace,
											name: marketplaceName(
												c.marketplace,
											),
										}}
										size={16}
									/>
									<span className="truncate">
										{marketplaceName(c.marketplace)}
									</span>
								</span>
							)}
							<span
								title={c.name ?? String(c.campaign_id)}
								className="min-w-0 flex-1 truncate text-sm text-content"
							>
								{c.name ?? c.campaign_id}
							</span>
							<span className="w-24 text-right text-sm font-medium text-content tabular-nums">
								{formatCurrency(c.ad_sales)}
							</span>
							<span className="w-20 text-right text-sm text-content-muted tabular-nums">
								{formatCurrency(c.budget_consumed)}
							</span>
							<span className="w-16 text-right text-sm text-content-muted tabular-nums">
								{c.budget_consumed
									? `${(c.ad_sales / c.budget_consumed).toFixed(2)}×`
									: "—"}
							</span>
							<span
								className={`w-24 text-right text-sm font-medium tabular-nums ${
									buBand(bu)?.text ?? "text-content-subtle"
								}`}
							>
								{bu == null ? "—" : `${bu.toFixed(0)}%`}
							</span>
							<span className="w-20 text-right text-sm text-content-muted tabular-nums">
								{formatNumber(c.impressions)}
							</span>
						</li>
					);
				})}
			</ul>

			{all.length > ROWS_SHOWN && (
				<button
					type="button"
					onClick={() => setExpanded((v) => !v)}
					className="mt-1 flex items-center justify-end gap-1 text-xs font-medium text-brand hover:underline"
				>
					{expanded
						? "Show fewer"
						: `View all ${formatNumber(all.length)} campaigns`}
					<ChevronDown
						size={13}
						aria-hidden
						className={`transition-transform ${expanded ? "rotate-180" : ""}`}
					/>
				</button>
			)}
		</div>
	);
};
