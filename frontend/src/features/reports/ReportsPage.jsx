import { useState } from "react";
import { Download } from "lucide-react";
import { getReportFile } from "./api";
import { useClient } from "../../context/ClientContext";
import { useDateRange } from "../../context/DateRangeContext";
import { useMarketplaces } from "../../context/MarketplaceContext";
import { ViewToggle } from "../../components/ui/ViewToggle";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import {
	SalesPivotReport,
	METRICS,
	GRANULARITY,
} from "./components/SalesPivotReport";
import { MarketingReport } from "./components/MarketingReport";
import { CompetitionReport, KINDS } from "./components/CompetitionReport";
import { WeekendPlanningReport } from "./components/WeekendPlanningReport";

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
	{ value: "weekend", label: "Weekend planning" },
	{ value: "marketing", label: "Marketing" },
	{ value: "competition", label: "Competition" },
];

// One line each, and no longer. The page header is not the place to explain a
// report; the report's own controls and column headers do that.
const SUBTITLES = {
	sales: "Sell-through per SKU, by day or by week.",
	weekend: "Campaign spend and return, weekend by weekend.",
	marketing: "Spend, revenue and what they returned, day by day.",
	competition: "Your price against competitors on the same search.",
};

export const ReportsPage = () => {
	const [report, setReport] = useState("sales");
	// Owned here so all three toggle groups render as one control row.
	const [metric, setMetric] = useState("value");
	const [granularity, setGranularity] = useState("daily");
	// Owned here so the Export button can send exactly what the table is showing.
	const [kind, setKind] = useState("main");
	const { activeClientId } = useClient();
	const { range } = useDateRange();
	const { selected } = useMarketplaces();
	const [exporting, setExporting] = useState(false);
	const [exportError, setExportError] = useState("");

	/**
	 * Download exactly what is on screen.
	 *
	 * ⚠️ It sends the SELECTION, not a fixed export: which report, the metric, the
	 * daily-or-weekly half of the pivot, the SKU kind, the window and the
	 * marketplace filter. The server renders from the same service that fed the
	 * table, so the workbook is the view the reader was looking at.
	 */
	const download = async () => {
		setExporting(true);
		setExportError("");
		try {
			const blob = await getReportFile(activeClientId, report, {
				start: range.from,
				end: range.to,
				marketplaces: selected,
				metric,
				view: granularity,
				kind,
			});
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `${report}_${range.from}_to_${range.to}.xlsx`;
			document.body.appendChild(a);
			a.click();
			a.remove();
			URL.revokeObjectURL(url);
		} catch (err) {
			// The server refuses a window it cannot render (no complete week, no data)
			// with a reason. Showing it beats a download that silently does nothing.
			setExportError(
				err?.response?.data?.detail ??
					err?.message ??
					"That report could not be built.",
			);
		} finally {
			setExporting(false);
		}
	};

	return (
		<div className="flex flex-col gap-6">
			{/* ⚠️ ONE control in the header. Three toggle groups stacked here read as a
			    settings bar rather than a page title, and two of the three only applied
			    to one report. The report picker stays; everything that changes the VIEW
			    of a report sits with that report, next to Export. */}
			<PageHeader
				title="Reports"
				subtitle={SUBTITLES[report]}
				actions={
					<ViewToggle
						options={REPORTS}
						value={report}
						onChange={setReport}
						size="lg"
					/>
				}
			/>

			<div className="mt-8 flex flex-wrap items-center justify-between gap-3">
				<div className="flex flex-wrap items-center gap-2">
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
					{report === "competition" && (
						<ViewToggle
							options={KINDS}
							value={kind}
							onChange={setKind}
						/>
					)}
				</div>
				<div className="flex flex-col items-end gap-1">
					<Button
						variant="brand"
						size="sm"
						disabled={exporting}
						onClick={download}
					>
						<Download size={14} />{" "}
						{exporting ? "Building…" : "Export to Excel"}
					</Button>
					{exportError && (
						<p className="text-xs text-danger">{exportError}</p>
					)}
				</div>
			</div>

			{report === "sales" && (
				<SalesPivotReport metric={metric} granularity={granularity} />
			)}
			{report === "marketing" && <MarketingReport />}
			{report === "weekend" && <WeekendPlanningReport />}
			{report === "competition" && <CompetitionReport kind={kind} />}
		</div>
	);
};
