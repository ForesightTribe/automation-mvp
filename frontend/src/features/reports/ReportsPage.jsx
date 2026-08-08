import { useState } from "react";
import { ViewToggle } from "../../components/ui/ViewToggle";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import {
	SalesPivotReport,
	METRICS,
	GRANULARITY,
} from "./components/SalesPivotReport";
import { MarketingReport } from "./components/MarketingReport";
import { CompetitionReport } from "./components/CompetitionReport";

/**
 * Reports — the client's familiar Excel views, rendered from the dashboard so
 * they can read the numbers directly instead of rebuilding pivots by hand. Each
 * report owns its own fetch (via the reports hooks) and the shared Navbar
 * client/date/marketplace selectors drive them. Blinkit-only today (that's the
 * data reality); other marketplaces arrive once their scrapers exist.
 *
 * Excel export is a deferred stub button; the marketing comments column and
 * budget targets are also deferred (they need manual-input tables).
 */

const REPORTS = [
	{ value: "sales", label: "Sales by SKU" },
	{ value: "marketing", label: "Marketing" },
	{ value: "competition", label: "Competition" },
];

const SUBTITLES = {
	sales: "Daily sell-through per SKU, by marketplace, with weekly rollups and week-over-week movement.",
	marketing: "Daily ad ledger — spend, revenue, RoAS, ROI — with budget pacing and marketing notes.",
	competition: "Own price vs competitors, normalized per unit (₹/100 ml · 100 g · piece) so different pack sizes compare fairly.",
};

export const ReportsPage = () => {
	const [report, setReport] = useState("sales");
	// Owned here so all three toggle groups render as one control row.
	const [metric, setMetric] = useState("value");
	const [granularity, setGranularity] = useState("daily");

	return (
		<div className="flex flex-col gap-6">
			<PageHeader
				title="Reports"
				subtitle={SUBTITLES[report]}
				actions={
					<div className="flex flex-wrap items-center justify-end gap-2">
						<ViewToggle
							options={REPORTS}
							value={report}
							onChange={setReport}
						/>
						{report === "sales" && (
							<>
								<ViewToggle
									options={METRICS}
									value={metric}
									onChange={setMetric}
								/>
								<ViewToggle
									options={GRANULARITY}
									value={granularity}
									onChange={setGranularity}
								/>
							</>
						)}
					</div>
				}
			/>

			{/* -mb pulls the table up: the page's gap-6 is right everywhere else,
			    but the export button belongs to the table below it. */}
			<div className="mt-10 -mb-4 flex justify-end">
				{/* Stub — export lands in a later phase. */}
				<Button
					variant="secondary"
					size="sm"
					disabled
					title="Excel export — coming soon"
				>
					⭳ Export to Excel
				</Button>
			</div>

			{report === "sales" && (
				<SalesPivotReport metric={metric} granularity={granularity} />
			)}
			{report === "marketing" && <MarketingReport />}
			{report === "competition" && <CompetitionReport />}
		</div>
	);
};
