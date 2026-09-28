import { useDateRange } from "../../../context/DateRangeContext";
import { ExportButton } from "../../../components/ui/ExportButton";
import { downloadCsv, exportName } from "../../../lib/exportTable";
import {
	useOverview,
	useTrends,
	useTopCampaigns,
	usePoSummary,
	useShareOfVoice,
	useTopCompetitors,
	usePricePosition,
} from "../hooks";

/**
 * The whole page as one file, section by section in the order it is read.
 *
 * Every hook here is already driving a panel on this page, so React Query serves
 * these from the same cache entries rather than fetching the page twice.
 *
 * Figures are exported RAW — full rupees, unrounded ratios — because the screen's
 * shortening exists to keep a column narrow, and a spreadsheet has no such
 * constraint and is where someone goes to do arithmetic on them.
 */
const pct = (v) => (v == null ? "" : (v * 100).toFixed(1));

export const OverviewExport = () => {
	const { range } = useDateRange();
	const { data: summary } = useOverview();
	const { data: trends } = useTrends();
	const { data: campaigns } = useTopCampaigns();
	const { data: po } = usePoSummary();
	const { data: sov } = useShareOfVoice();
	const { data: comp } = useTopCompetitors();
	const { data: price } = usePricePosition();

	const sections = () => {
		const out = [];

		if (summary) {
			out.push({
				title: `Overview, ${range.from} to ${range.to}`,
				columns: [
					{ header: "Metric", value: (r) => r.label },
					{ header: "Value", value: (r) => r.value },
					{ header: "Previous period", value: (r) => r.prev },
					{ header: "Change %", value: (r) => pct(r.delta) },
				],
				rows: [
					["Revenue", summary.revenue],
					["Ad revenue", summary.ad_sales],
					["Ad spend", summary.ad_spend],
					["Organic revenue", summary.organic_revenue],
				]
					.filter(([, m]) => m)
					.map(([label, m]) => ({
						label,
						value: m.value,
						prev: m.prev,
						delta: m.delta_pct,
					}))
					.concat(
						summary.roas
							? [
									{
										label: "RoAS",
										value: summary.roas.value,
										prev: summary.roas.prev,
										delta: summary.roas.delta_pct,
									},
								]
							: [],
					),
			});
		}

		if (trends?.length) {
			out.push({
				title: "Revenue by day",
				columns: [
					{ header: "Date", value: (r) => r.date },
					{ header: "Revenue", value: (r) => r.revenue },
					{ header: "Ad revenue", value: (r) => r.ad_sales },
					{ header: "Ad spend", value: (r) => r.ad_spend },
					{
						header: "Organic revenue",
						value: (r) =>
							r.revenue == null || r.ad_sales == null
								? ""
								: r.revenue - r.ad_sales,
					},
				],
				rows: trends,
			});
		}

		const camps = (campaigns?.items ?? []).filter((c) => c.ad_sales > 0);
		if (camps.length) {
			out.push({
				title: "Campaigns",
				columns: [
					{
						header: "Campaign",
						value: (r) => r.name ?? r.campaign_id,
					},
					{ header: "Type", value: (r) => r.type },
					{ header: "Spend", value: (r) => r.budget_consumed },
					{ header: "Ad revenue", value: (r) => r.ad_sales },
					{ header: "RoAS", value: (r) => r.roas?.toFixed(2) },
					{ header: "Daily budget", value: (r) => r.daily_budget },
				],
				rows: camps,
			});
		}

		if (po) {
			// Fill rate and missed value are left blank rather than zero when no
			// PO has closed: nothing has been judged yet, and a zero would read
			// as a clean sheet.
			const judged = (po.closed_pos ?? 0) > 0;
			out.push({
				title: "Purchase orders",
				columns: [
					{ header: "Metric", value: (r) => r[0] },
					{ header: "Value", value: (r) => r[1] },
				],
				rows: [
					["Ordered", po.po_value],
					["Previous period", po.prev_po_value],
					["Open POs", po.open_pos],
					["Open, not yet delivered", po.value_at_risk],
					["Closed POs", po.closed_pos],
					["Closed short", judged ? po.short_pos : ""],
					["Fill rate %", judged ? pct(po.fill_rate) : ""],
					["Missed", judged ? po.value_missed : ""],
				],
			});
		}

		if (sov?.summary) {
			out.push({
				title: "Visibility",
				columns: [
					{ header: "Metric", value: (r) => r[0] },
					{ header: "Value", value: (r) => r[1] },
				],
				rows: [
					["Latest share of voice %", sov.summary.latest_sov],
					["Period average share of voice %", sov.summary.avg_sov],
					["Average rank", sov.summary.avg_rank],
					["Scraped days", sov.trend?.length ?? 0],
				],
			});
		}

		if (comp?.competitors?.length) {
			out.push({
				title: "Competitors",
				columns: [
					{ header: "Competitor", value: (r) => r.competitor },
					{ header: "Stores", value: (r) => r.stores },
					{ header: "Keywords", value: (r) => r.keywords },
					{ header: "Avg rank", value: (r) => r.avg_position },
					{ header: "Avg price", value: (r) => r.avg_price },
					{
						header: "Share of competitors %",
						value: (r) => r.share_pct,
					},
				],
				rows: comp.competitors,
			});
		}

		const priceRows = (price?.rows ?? []).filter(
			(r) => r.own_avg_unit_price != null && r.comp_median_unit_price > 0,
		);
		if (priceRows.length) {
			out.push({
				// The product counts ship with it: `*_samples` count listing rows
				// and overstate the basis by orders of magnitude, so a reader
				// working in the sheet needs the real denominator beside the
				// prices.
				title: "Price position (per unit)",
				columns: [
					{ header: "Keyword", value: (r) => r.keyword },
					{ header: "Basis", value: (r) => r.unit_uom },
					{ header: "Our avg", value: (r) => r.own_avg_unit_price },
					{
						header: "Market median",
						value: (r) => r.comp_median_unit_price,
					},
					{
						header: "Multiple",
						value: (r) =>
							(
								r.own_avg_unit_price / r.comp_median_unit_price
							).toFixed(2),
					},
					{ header: "Our products", value: (r) => r.own_products },
					{
						header: "Competitor products",
						value: (r) => r.comp_products,
					},
				],
				rows: priceRows,
			});
		}

		return out;
	};

	const ready = Boolean(summary || trends?.length);

	return (
		<ExportButton
			label="Export overview"
			disabled={!ready}
			onExport={() =>
				downloadCsv(exportName("overview", range), sections())
			}
		/>
	);
};
