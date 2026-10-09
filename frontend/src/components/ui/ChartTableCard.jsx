import { useState } from "react";
import { Card } from "./Card";
import { ChartTableSwitch } from "./ChartTableSwitch";
import { DataTable } from "./DataTable";
import { Loading } from "../feedback/Loading";
import { ErrorState } from "../feedback/ErrorState";
import { EmptyState } from "../feedback/EmptyState";

/**
 * A Card that flips between a chart and a table of the same data. Owns the
 * Chart/Table view state and the standard loading/error/empty handling, so each
 * section component stays thin: it passes a `renderChart` thunk plus the table
 * `columns`/`rows`. `extraActions` (e.g. a metric toggle) shows only in chart
 * view, since the table renders every column anyway; `persistentActions` (e.g. a
 * grouping toggle, which reshapes both views) shows in both.
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
	persistentActions,
	// Controls that belong with the content rather than the title — they share
	// the switch's row, left-aligned against it.
	toolbar,
}) => {
	const [view, setView] = useState("chart");

	// Header actions are about the card; the view switch sits with the content.
	const actions = (
		<div className="flex items-center gap-2">
			{persistentActions}
			{view === "chart" && extraActions}
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
				) : (
					<div className="flex flex-col gap-2">
						<div className="flex flex-wrap items-center justify-between gap-2">
							<div className="min-w-0">{toolbar}</div>
							<ChartTableSwitch value={view} onChange={setView} />
						</div>
						{view === "chart" ? (
							renderChart()
						) : (
							<DataTable
								columns={columns}
								rows={rows}
								rowKey={rowKey}
								maxHeight={tableMaxHeight}
							/>
						)}
					</div>
				))}
		</Card>
	);
};
