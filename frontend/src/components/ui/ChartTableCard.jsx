import { useState } from "react";
import { Card } from "./Card";
import { ViewToggle } from "./ViewToggle";
import { DataTable } from "./DataTable";
import { Loading } from "../feedback/Loading";
import { ErrorState } from "../feedback/ErrorState";
import { EmptyState } from "../feedback/EmptyState";

const VIEW_OPTIONS = [
	{ value: "chart", label: "Chart" },
	{ value: "table", label: "Table" },
];

/**
 * A Card that flips between a chart and a table of the same data. Owns the
 * Chart/Table view state and the standard loading/error/empty handling, so each
 * section component stays thin: it passes a `renderChart` thunk plus the table
 * `columns`/`rows`. `extraActions` (e.g. a metric toggle) shows only in chart
 * view, since the table renders every column anyway.
 */
export const ChartTableCard = ({
	title,
	isLoading,
	error,
	refetch,
	isEmpty,
	emptyMessage = "No data in this window.",
	renderChart,
	columns,
	rows,
	rowKey,
	tableMaxHeight,
	extraActions,
}) => {
	const [view, setView] = useState("chart");

	const actions = (
		<div className="flex items-center gap-2">
			{view === "chart" && extraActions}
			<ViewToggle options={VIEW_OPTIONS} value={view} onChange={setView} />
		</div>
	);

	return (
		<Card title={title} actions={actions}>
			{isLoading && <Loading label="Loading…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(isEmpty ? (
					<EmptyState message={emptyMessage} />
				) : view === "chart" ? (
					renderChart()
				) : (
					<DataTable
						columns={columns}
						rows={rows}
						rowKey={rowKey}
						maxHeight={tableMaxHeight}
					/>
				))}
		</Card>
	);
};
