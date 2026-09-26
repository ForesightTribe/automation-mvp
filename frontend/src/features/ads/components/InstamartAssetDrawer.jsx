import { Drawer, DrawerStat } from "../../../components/ui/Drawer";
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
 * One Instamart product or keyword in full, opened from the Ad asset
 * performance card. Same shell as Blinkit's KeywordDrawer, but only the
 * sections Instamart's data actually supports — no Direct/Indirect split, no
 * match type, no position: Instamart's advertiser/metrics API reports none
 * of those (checked live; see asset_metrics.py). "By campaign" only has rows
 * when a specific ad type is selected on the card — the unfiltered "All ad
 * types" total has no campaign id to attribute with, same reason the
 * Campaign column reads "—" there.
 *
 * Read-only, same as Blinkit's.
 */
export const InstamartAssetDrawer = ({ row, range, open, onClose }) => {
	if (!open || !row) return null;

	const isProduct = row._dim === "product";
	const name = isProduct
		? (row.product_name ?? row.product_variant_id)
		: row.keyword;
	const campaigns = row.campaigns ?? [];
	const acos = row.sales ? (row.spend / row.sales) * 100 : null;

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={name}
			subtitle={
				campaigns.length
					? `${campaigns.length} campaign${campaigns.length === 1 ? "" : "s"}`
					: "No campaign breakdown for this date range yet"
			}
			stats={
				<>
					<DrawerStat label="Spend" value={formatCurrency(row.spend)} />
					<DrawerStat label="GMV" value={formatCurrency(row.sales)} />
					<DrawerStat label="RoAS" value={roas(row.roas)} />
				</>
			}
		>
			<Section
				title="Performance"
				hint={range ? `${range.from} to ${range.to}` : ""}
			>
				<Rows
					pairs={[
						["Impressions", formatNumber(row.impressions)],
						["Clicks", formatNumber(row.clicks)],
						["CTR", pct(row.ctr)],
						["Add to cart", formatNumber(row.atc)],
						["ACoS", pct(acos)],
						[
							"CPC",
							row.cpc == null ? dash : formatCurrency(row.cpc),
						],
						[
							"CPM",
							row.cpm == null ? dash : formatCurrency(row.cpm),
						],
					]}
				/>
			</Section>

			<Section
				title="By campaign"
				hint={`${campaigns.length} row${campaigns.length === 1 ? "" : "s"}`}
			>
				{campaigns.length === 0 ? (
					<p className="text-sm text-content-muted">
						No campaign-level data scraped for this date range
						yet — the campaign breakdown only covers the shorter
						window the ad-type scrape has run over.
					</p>
				) : (
					<table className="w-full text-sm">
						<tbody>
							{campaigns.map((c) => (
								<tr
									key={c.campaign_id}
									className="border-b border-border/60 last:border-0"
								>
									<td className="max-w-[16rem] truncate py-1.5 pr-2 text-content">
										{c.campaign_name}
									</td>
									<td className="py-1.5 pr-2 text-right tabular-nums text-content">
										{formatCurrency(c.spend)}
									</td>
									<td className="py-1.5 pr-2 text-right tabular-nums text-content-muted">
										{formatCurrency(c.sales)}
									</td>
									<td className="py-1.5 text-right tabular-nums text-content-muted">
										{roas(c.spend ? c.sales / c.spend : null)}
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
