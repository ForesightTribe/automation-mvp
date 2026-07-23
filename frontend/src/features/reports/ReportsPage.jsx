import { useState } from "react";
import { ViewToggle } from "../../components/ui/ViewToggle";
import { Button } from "../../components/ui/Button";
import { SalesPivotReport } from "./components/SalesPivotReport";
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
	competition: "Own price vs competitors, normalized per gram so different pack sizes compare fairly.",
};

export const ReportsPage = () => {
	const [report, setReport] = useState("sales");

	return (
		<div className="flex flex-col gap-6">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<h1 className="font-display text-xl font-bold text-content">
						Reports
					</h1>
					<p className="text-sm text-content-muted">{SUBTITLES[report]}</p>
				</div>
				<div className="flex items-center gap-2">
					<ViewToggle
						options={REPORTS}
						value={report}
						onChange={setReport}
					/>
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
			</div>

			{report === "sales" && <SalesPivotReport />}
			{report === "marketing" && <MarketingReport />}
			{report === "competition" && <CompetitionReport />}
		</div>
	);
};
