import { useMemo } from "react";
import { Drawer } from "../../../components/ui/Drawer";
import { EChart } from "../../../components/charts/EChart";
import { buCompareOption } from "../chartOptions";
import { buBand } from "../buBands";
import { campaignKey, useDailyBudgetUtilisation } from "../hooks";
import { Loading } from "../../../components/feedback/Loading";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatDate } from "../../../lib/format";

const pct = (v) => (v == null ? "—" : `${v.toFixed(1)}%`);

// A shared empty array, so "no data yet" does not hand the chart a new identity each render.
const NO_DAYS = [];

/** One cell of the drawer's stat strip. The strip is a 3-column grid of these. */
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
 * The deep dive behind a campaign's budget-utilisation figure.
 *
 * The table shows one number for the window; this is what that number is made of. The per
 * day data costs one request per day, so it is fetched HERE, on open, rather than by the
 * table: a column of 20 campaigns would otherwise pay for the detail of 20 campaigns nobody
 * asked about.
 *
 * It deliberately shows TWO averages. The table's figure measures spend against every day in
 * the window, including days the campaign was switched off; the second measures only the
 * days it actually ran. They answer different questions ("did we spend what we set aside"
 * against "when it ran, did it use its budget"), and a reader who sees only one of them
 * eventually finds the other and assumes something is broken.
 */
export const BuDetailDrawer = ({ open, campaign, onClose }) => {
	// Follows the page's date picker rather than offering a second one. Two period
	// controls on one screen is two places to look for the same answer.
	const { campaigns, dates, isLoading } = useDailyBudgetUtilisation({
		enabled: open,
	});

	// By marketplace AND id: ids are per-marketplace namespaces.
	const row = campaign
		? campaigns.find((c) => c.key === campaignKey(campaign))
		: undefined;
	const days = row?.days ?? NO_DAYS;
	const ran = days.filter((d) => d.bu != null);
	const spend = ran.reduce((s, d) => s + d.spend, 0);
	const allowedRan = ran.reduce((s, d) => s + d.allowed, 0);
	const sales = ran.reduce((s, d) => s + (d.sales ?? 0), 0);
	// Recomputed from the totals, never averaged from the daily ratios: a mean of ratios is
	// not the ratio of the sums, and the difference is largest on the days that matter least.
	const roas = spend ? sales / spend : null;
	const chart = useMemo(() => buCompareOption(days), [days]);

	// Measured across the days the campaign actually ran: a day it was switched off had no
	// budget on the table, so counting it as unused budget would read as a failure to spend.
	const onDays = allowedRan ? (spend / allowedRan) * 100 : null;

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title="Budget utilisation"
			subtitle={
				dates.length
					? `${campaign?.name ?? ""} · ${formatDate(dates[0])} to ${formatDate(dates[dates.length - 1])}`
					: campaign?.name
			}
			// Held back until every day is in: a strip that reads "2 of 2 days" while 28 more
			// are still arriving is worse than no strip at all.
			stats={
				!isLoading && ran.length ? (
					<>
						<Stat label="Budget used" value={pct(onDays)} />
						<Stat label="Ad spend" value={formatCurrency(spend)} />
						<Stat
							label="RoAS"
							value={roas == null ? "—" : `${roas.toFixed(2)}x`}
						/>
					</>
				) : undefined
			}
		>
			{isLoading && <Loading label="Loading each day…" />}
			{!isLoading && !ran.length && (
				<EmptyState message="This campaign did not run on any day in this window, so there was no budget to use." />
			)}
			{!isLoading && ran.length > 0 && (
				<div className="flex flex-col gap-4">
					<div className="rounded-lg border border-border p-3">
						<p className="mb-1 text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
							Spend against budget
						</p>
						{/* Spend against the ceiling it was allowed. The distance between the lines is
						    the money left unspent, which is the thing this drawer exists to show. */}
						<EChart option={chart} height={240} />
					</div>

					<div>
						<p className="mb-2 text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
							Day by day
						</p>
						<table className="w-full border-collapse text-sm">
							<thead>
								<tr className="border-b border-border text-[11px] tracking-[0.08em] text-content-subtle uppercase">
									<th className="px-2 py-2 text-left font-semibold">
										Date
									</th>
									<th className="px-2 py-2 text-right font-semibold">
										Used
									</th>
									<th className="px-2 py-2 text-right font-semibold">
										Spend
									</th>
									<th className="px-2 py-2 text-right font-semibold">
										Budget
									</th>
									<th className="px-2 py-2 text-right font-semibold">
										Sales
									</th>
									<th className="px-2 py-2 text-right font-semibold">
										RoAS
									</th>
								</tr>
							</thead>
							<tbody>
								{days.map((d) => (
									<tr
										key={d.date}
										className="border-b border-border/60 last:border-0"
									>
										<td className="px-2 py-1.5 text-content">
											{formatDate(d.date)}
										</td>
										{/* The figure carries its own band colour. The number is still printed,
										    so the hue speeds the scan rather than being the only signal. */}
										<td className="px-2 py-1.5 text-right font-medium tabular-nums">
											{d.bu == null ? (
												<span className="font-normal text-content-subtle">
													did not run
												</span>
											) : (
												<span
													className={
														buBand(d.bu).text
													}
												>
													{pct(d.bu)}
												</span>
											)}
										</td>
										<td className="px-2 py-1.5 text-right tabular-nums text-content-muted">
											{d.spend == null
												? "—"
												: formatCurrency(d.spend)}
										</td>
										<td className="px-2 py-1.5 text-right tabular-nums text-content-muted">
											{d.allowed == null
												? "—"
												: formatCurrency(d.allowed)}
										</td>
										<td className="px-2 py-1.5 text-right tabular-nums text-content-muted">
											{d.sales == null
												? "—"
												: formatCurrency(d.sales)}
										</td>
										<td className="px-2 py-1.5 text-right font-medium tabular-nums text-content">
											{d.roas == null
												? "—"
												: `${d.roas.toFixed(2)}x`}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				</div>
			)}
		</Drawer>
	);
};
