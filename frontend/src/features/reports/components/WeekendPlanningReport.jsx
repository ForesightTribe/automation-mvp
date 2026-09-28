import { Fragment } from "react";
import { useWeekendPlanning } from "../hooks";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { WorkbookView } from "./WorkbookView";
import { RawAdSheet, INSTAMART_RAW_COLS } from "./RawAdSheet";
import { HoverHint } from "../../../components/ui/HoverHint";
import { formatCurrency, formatNumber } from "../../../lib/format";

/**
 * Weekend planning — the client's own workbook, on screen.
 *
 * Campaigns down the side grouped by ad type, one column group per Fri–Sun
 * weekend, an all-weekend Grand Total, and Max Spends: the highest average day
 * of spend a campaign reached in any single weekend. That last column is the
 * point of the sheet, since it is the ceiling a campaign has demonstrated rather
 * than a budget someone hopes it will use.
 *
 * ⚠️ These are SUMS. One weekend against another is like for like, unlike the
 * sales report's weekday/weekend split, which compares four days with three and
 * therefore averages.
 *
 * The two raw sheets of the workbook are download-only: eighteen thousand rows
 * is a file, not a page.
 */
const ROAS = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);

/**
 * ⚠️ Column groups are separated by a RULE, not a tint.
 *
 * A tint cannot carry the boundary here: a fraction of `--color-muted` on
 * `--color-card`, on a page whose own background is `--color-surface`, puts three
 * near-identical creams side by side and none of them reads as an edge. A vertical
 * rule is unambiguous at any tint, which also leaves the table's one fill reserved
 * for TOTALS rows, so a filled row always means the same thing.
 */
const GROUP = "border-l-2 border-border";

const TH =
	"px-3 py-2 text-[11px] font-semibold tracking-[0.08em] uppercase whitespace-nowrap";
const TD = "px-3 py-2 whitespace-nowrap";
const NUM = `${TD} text-right tabular-nums`;

const Trio = ({ half }) => (
	<>
		<td className={`${NUM} ${GROUP}`}>{formatCurrency(half.spend)}</td>
		<td className={NUM}>{formatCurrency(half.revenue)}</td>
		<td className={`${NUM} font-medium`}>{ROAS(half.roas)}</td>
	</>
);

const TrioHead = () => (
	<>
		<th className={`${TH} ${GROUP} bg-surface text-right`}>Spends</th>
		<th className={`${TH} bg-surface text-right`}>Revenue</th>
		<th className={`${TH} bg-surface text-right`}>ROAS</th>
	</>
);

export const WeekendPlanningReport = () => {
	const { data, isLoading, error, refetch } = useWeekendPlanning();
	const { selected } = useMarketplaces();
	const wantsBlinkit = selected.includes("blinkit");
	const wantsInstamart = selected.includes("instamart");

	if (isLoading) return <Loading label="Loading weekend planning…" />;
	if (error) return <ErrorState message={error.message} onRetry={refetch} />;
	if (!data?.sections?.length)
		return <EmptyState message="No campaign activity in this window." />;

	const { weekends, sections, totals, banners } = data;

	const row = (c, label, bold) => (
		<tr
			key={`${label ?? ""}-${c.campaign_id}-${c.name}`}
			className={`border-b border-border/60 last:border-0 ${
				bold ? "bg-muted font-semibold" : "hover:bg-muted"
			}`}
		>
			<td
				className={`${TD} sticky left-0 z-10 ${bold ? "bg-muted" : "bg-card"} text-content-muted`}
			>
				{label ?? ""}
			</td>
			<td
				className={`${TD} max-w-[18rem] truncate font-medium text-content`}
				title={c.name}
			>
				{c.name}
			</td>
			{c.weekends.map((half, i) => (
				<Trio key={i} half={half} />
			))}
			<Trio half={c.weekend_total} />
			<td
				className={`${NUM} border-l border-border font-medium text-content`}
			>
				{formatCurrency(c.max_daily_spend)}
			</td>
		</tr>
	);

	const planningSheet = () => (
		<table className="w-full border-collapse text-sm">
			<thead className="sticky top-0 z-30">
				<tr className="border-b border-border">
					<th
						colSpan={2}
						className={`${TH} sticky left-0 z-40 bg-surface text-left`}
					/>
					{weekends.map((w) => (
						<th
							key={w.label}
							colSpan={3}
							className={`${TH} ${GROUP} bg-surface text-center text-content`}
						>
							{w.label}
						</th>
					))}
					<th
						colSpan={3}
						className={`${TH} border-l border-border bg-surface text-center text-content`}
					>
						Grand Total
					</th>
					<th
						className={`${TH} ${GROUP} bg-surface text-right text-content`}
					>
						<HoverHint
							label="The highest average day of spend this campaign reached in any single weekend. It is the ceiling it has demonstrated, not a target."
							className="w-full justify-end"
							tabIndex={0}
						>
							<span className="cursor-help decoration-content-subtle/40 decoration-dotted underline-offset-4 hover:underline">
								Max Spends
							</span>
						</HoverHint>
					</th>
				</tr>
				<tr className="border-b border-border text-content-subtle">
					<th
						className={`${TH} sticky left-0 z-40 bg-surface text-left`}
					>
						Ad Type
					</th>
					<th className={`${TH} bg-surface text-left`}>
						Campaign Name
					</th>
					{weekends.map((w) => (
						<TrioHead key={w.label} />
					))}
					<TrioHead />
					<th className={`${TH} ${GROUP} bg-surface text-right`}>
						per day
					</th>
				</tr>
			</thead>
			<tbody>
				{sections.map((sec) => (
					<Fragment key={sec.ad_type}>
						{sec.campaigns.map((c, i) =>
							row(c, i === 0 ? sec.label : null, false),
						)}
						{row(sec.subtotal, null, true)}
					</Fragment>
				))}
				<tr className="border-t-2 border-content bg-muted font-semibold">
					<td
						className={`${TD} sticky left-0 z-10 bg-muted`}
						colSpan={2}
					>
						Grand Total
					</td>
					{totals.weekends.map((half, i) => (
						<Trio key={i} half={half} />
					))}
					<Trio half={totals.weekend_total} />
					<td className={`${NUM} border-l border-border`}>
						{formatCurrency(totals.max_daily_spend)}
					</td>
				</tr>
			</tbody>
		</table>
	);

	const weekdaySheet = () => (
		<table className="w-full border-collapse text-sm">
			<thead className="sticky top-0 z-20">
				<tr className="border-b border-border text-content-subtle">
					<th className={`${TH} bg-surface text-left`}>Ad Type</th>
					<th className={`${TH} bg-surface text-left`}>
						Campaign Name
					</th>
					<th className={`${TH} bg-surface text-right`}>Spends</th>
					<th className={`${TH} bg-surface text-right`}>Revenue</th>
					<th className={`${TH} bg-surface text-right`}>ROAS</th>
				</tr>
			</thead>
			<tbody>
				{sections.flatMap((sec) =>
					sec.campaigns.map((c, i) => (
						<tr
							key={c.campaign_id}
							className="border-b border-border/60 hover:bg-muted"
						>
							<td className={`${TD} text-content-muted`}>
								{i === 0 ? sec.label : ""}
							</td>
							<td
								className={`${TD} max-w-[22rem] truncate font-medium text-content`}
								title={c.name}
							>
								{c.name}
							</td>
							<td className={NUM}>
								{formatCurrency(c.weekday.spend)}
							</td>
							<td className={NUM}>
								{formatCurrency(c.weekday.revenue)}
							</td>
							<td className={`${NUM} font-medium`}>
								{ROAS(c.weekday.roas)}
							</td>
						</tr>
					)),
				)}
				<tr className="border-t-2 border-content bg-muted font-semibold">
					<td className={TD} colSpan={2}>
						Grand Total
					</td>
					<td className={NUM}>
						{formatCurrency(totals.weekday.spend)}
					</td>
					<td className={NUM}>
						{formatCurrency(totals.weekday.revenue)}
					</td>
					<td className={NUM}>{ROAS(totals.weekday.roas)}</td>
				</tr>
			</tbody>
		</table>
	);

	const bannerSheet = () => (
		<table className="w-full border-collapse text-sm">
			<thead className="sticky top-0 z-20">
				<tr className="border-b border-border text-content-subtle">
					<th className={`${TH} bg-surface text-left`}>
						Campaign Name
					</th>
					<th className={`${TH} bg-surface text-right`}>Spends</th>
					<th className={`${TH} bg-surface text-right`}>
						Impressions
					</th>
					<th className={`${TH} bg-surface text-right`}>
						Spend per 1,000 impressions
					</th>
				</tr>
			</thead>
			<tbody>
				{banners.map((b) => (
					<tr
						key={b.campaign_id}
						className="border-b border-border/60 hover:bg-muted"
					>
						<td
							className={`${TD} max-w-[26rem] truncate font-medium text-content`}
							title={b.name}
						>
							{b.name}
						</td>
						<td className={NUM}>{formatCurrency(b.spend)}</td>
						<td className={NUM}>{formatNumber(b.impressions)}</td>
						<td className={`${NUM} font-medium`}>
							{b.spend_per_impression == null
								? "—"
								: formatCurrency(b.spend_per_impression)}
						</td>
					</tr>
				))}
			</tbody>
		</table>
	);

	const sheets = [
		{
			key: "planning",
			label: "Weekend Planning",
			render: planningSheet,
		},
		{
			key: "weekday",
			label: "Weekday Performance",
			render: weekdaySheet,
		},
	];
	if (banners.length) {
		sheets.push({
			key: "banners",
			label: "Banner Listing Ads",
			render: bannerSheet,
		});
	}

	// The workbook's raw sheets are tabs like any other, fetched only when opened.
	// Which ones show depends on the marketplace picker: Blinkit's two raw
	// exports and Instamart's one flat export are different tables, so a raw
	// tab only appears for a marketplace it actually belongs to — otherwise it
	// silently shows Blinkit rows under an Instamart-only selection (see
	// instamart_reports.raw_ad_rows for why Instamart's is one sheet, not two).
	if (wantsBlinkit) {
		sheets.push(
			{
				key: "raw_listing",
				label: "PRODUCT_LISTING",
				render: (active) => (
					<RawAdSheet campaignType="PRODUCT_LISTING" active={active} />
				),
			},
			{
				key: "raw_reco",
				label: "PRODUCT_RECOMMENDATION",
				render: (active) => (
					<RawAdSheet
						campaignType="PRODUCT_RECOMMENDATION"
						active={active}
					/>
				),
			},
		);
	}
	if (wantsInstamart) {
		sheets.push({
			key: "raw_instamart",
			label: "INSTAMART RAW",
			render: (active) => (
				<RawAdSheet
					marketplace="instamart"
					columns={INSTAMART_RAW_COLS}
					active={active}
				/>
			),
		});
	}

	return <WorkbookView sheets={sheets} />;
};
