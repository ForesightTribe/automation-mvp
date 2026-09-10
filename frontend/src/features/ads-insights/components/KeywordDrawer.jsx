import { useMemo } from "react";
import { Drawer } from "../../../components/ui/Drawer";
import { useCampaigns } from "../hooks";
import { enumLabel } from "./insightsTable";
import { formatCurrency, formatNumber } from "../../../lib/format";

const dash = "—";
const roas = (v) => (v == null ? dash : `${v.toFixed(2)}x`);
const pct = (v) => (v == null ? dash : `${v.toFixed(1)}%`);

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

const Rows = ({ pairs }) => (
	<dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
		{pairs.map(([k, v]) => (
			<div
				key={k}
				className="flex justify-between gap-3 border-b border-border/60 py-1"
			>
				<dt className="text-content-muted">{k}</dt>
				<dd className="tabular-nums text-content">{v}</dd>
			</div>
		))}
	</dl>
);

/**
 * One keyword in full, opened from the table.
 *
 * A keyword is not one row. The same term can be bid on in several campaigns, each with its
 * own spend and its own result, so the header totals every campaign it runs in and the last
 * section breaks them out. A keyword that runs in one campaign shows the same number twice,
 * which is the honest answer rather than a hidden special case.
 *
 * Read-only. Acting on a keyword belongs in Ad Automation, so opening a detail view can
 * never be what changes a live account.
 */
export const KeywordDrawer = ({ target, rows, range, open, onClose }) => {
	const mine = useMemo(
		() => (rows ?? []).filter((r) => r.target === target),
		[rows, target],
	);

	// The keyword rows carry only a campaign id, and an id names nothing to a reader.
	const { data: campaignPage } = useCampaigns({
		page: 1,
		limit: 250,
		sort: "spend",
		order: "desc",
	});
	const nameOf = useMemo(() => {
		const by = new Map(
			(campaignPage?.items ?? []).map((c) => [
				String(c.campaign_id),
				c.name,
			]),
		);
		return (id) => by.get(String(id)) ?? String(id);
	}, [campaignPage]);

	const totals = useMemo(() => {
		const sum = (pick) => mine.reduce((s, r) => s + (pick(r) ?? 0), 0);
		const spend = sum((r) => r.budget_consumed);
		const direct = sum((r) => r.direct_sales);
		const indirect = sum((r) => r.indirect_sales);
		const total = direct + indirect;
		const impressions = sum((r) => r.impressions);
		// Positions are per campaign and cannot be summed. The best one is the useful
		// reading: it is the nearest this keyword got to the top anywhere it ran.
		const seen = mine
			.map((r) => r.most_viewed_position)
			.filter((p) => p != null);
		return {
			spend,
			direct,
			indirect,
			total,
			impressions,
			atc: sum((r) => (r.direct_atc ?? 0) + (r.indirect_atc ?? 0)),
			roas: spend ? total / spend : null,
			directRoas: spend ? direct / spend : null,
			acos: total ? (spend / total) * 100 : null,
			cpm: impressions ? (spend / impressions) * 1000 : null,
			bestPosition: seen.length ? Math.min(...seen) : null,
			matches: [
				...new Set(mine.map((r) => r.match_type).filter(Boolean)),
			],
		};
	}, [mine]);

	if (!open) return null;

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={target}
			subtitle={`${mine.length} campaign${mine.length === 1 ? "" : "s"}${
				totals.matches.length ? ` · ${totals.matches.join(", ")}` : ""
			}`}
			stats={
				<>
					<Stat label="Spend" value={formatCurrency(totals.spend)} />
					<Stat
						label="Total sales"
						value={formatCurrency(totals.total)}
					/>
					<Stat label="RoAS" value={roas(totals.roas)} />
				</>
			}
		>
			<Section
				title="Performance"
				hint={range ? `${range.from} to ${range.to}` : ""}
			>
				<Rows
					pairs={[
						["Direct sales", formatCurrency(totals.direct)],
						["Indirect sales", formatCurrency(totals.indirect)],
						["Direct RoAS", roas(totals.directRoas)],
						["ACoS", pct(totals.acos)],
						["Impressions", formatNumber(totals.impressions)],
						["Add to cart", formatNumber(totals.atc)],
						[
							"Average CPM",
							totals.cpm == null
								? dash
								: formatCurrency(totals.cpm),
						],
						[
							"Best position seen",
							totals.bestPosition == null
								? dash
								: `#${totals.bestPosition}`,
						],
					]}
				/>
			</Section>

			<Section
				title="Direct against indirect"
				hint="what the ad sold, and what it sold alongside"
			>
				{/* One split bar rather than a chart: two parts of one total is a proportion,
				    and a proportion is read off a single bar faster than off two columns. The
				    figures stay beside it, because a bar alone cannot be read precisely. */}
				{totals.total === 0 ? (
					<p className="text-sm text-content-muted">
						No sales attributed to this keyword in this window.
					</p>
				) : (
					<>
						<div className="flex h-3 overflow-hidden rounded-full bg-muted">
							<span
								className="block bg-brand"
								style={{
									width: `${(totals.direct / totals.total) * 100}%`,
								}}
							/>
							<span
								className="block bg-brand-soft"
								style={{
									width: `${(totals.indirect / totals.total) * 100}%`,
								}}
							/>
						</div>
						<div className="mt-2 flex justify-between text-sm">
							<span className="flex items-center gap-1.5 text-content">
								<span className="h-2 w-2 rounded-full bg-brand" />
								Direct {formatCurrency(totals.direct)}
								<span className="text-content-subtle tabular-nums">
									{pct((totals.direct / totals.total) * 100)}
								</span>
							</span>
							<span className="flex items-center gap-1.5 text-content-muted">
								<span className="h-2 w-2 rounded-full bg-brand-soft" />
								Indirect {formatCurrency(totals.indirect)}
								<span className="text-content-subtle tabular-nums">
									{pct(
										(totals.indirect / totals.total) * 100,
									)}
								</span>
							</span>
						</div>
					</>
				)}
			</Section>

			<Section
				title="By campaign"
				hint={`${mine.length} row${mine.length === 1 ? "" : "s"}`}
			>
				{mine.length === 0 ? (
					<p className="text-sm text-content-muted">
						No rows for this keyword in the loaded set.
					</p>
				) : (
					<table className="w-full text-sm">
						<tbody>
							{[...mine]
								.sort(
									(a, b) =>
										(b.budget_consumed ?? 0) -
										(a.budget_consumed ?? 0),
								)
								.map((r, i) => (
									<tr
										key={`${r.campaign_id}-${r.match_type ?? ""}-${i}`}
										className="border-b border-border/60 last:border-0"
									>
										<td className="max-w-[14rem] truncate py-1.5 pr-2 text-content">
											{nameOf(r.campaign_id)}
										</td>
										<td className="py-1.5 pr-2 text-content-muted">
											{enumLabel(r.match_type)}
										</td>
										<td className="py-1.5 text-right tabular-nums text-content">
											{formatCurrency(
												r.budget_consumed ?? 0,
											)}
										</td>
										<td className="py-1.5 text-right tabular-nums text-content-muted">
											{roas(r.total_roas)}
										</td>
										<td className="py-1.5 text-right tabular-nums text-content-muted">
											{r.most_viewed_position == null
												? dash
												: `#${r.most_viewed_position}`}
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
