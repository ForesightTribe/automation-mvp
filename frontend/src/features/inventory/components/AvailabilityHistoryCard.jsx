import { useMemo } from "react";
import { useAvailabilityHistory } from "../hooks";
import { EChart } from "../../../components/charts/EChart";
import { ChartTableCard } from "../../../components/ui/ChartTableCard";
import { availabilityTrendOption } from "../../../components/charts/options";
import { formatDate, formatNumber } from "../../../lib/format";

const pct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`);

/**
 * Weekly on-shelf availability % for own SKUs — the stock-out trend. One point per
 * weekly scrape; fills in as runs accumulate. Table view shows the exact
 * availability / OOS split and sample count per week.
 */
export const AvailabilityHistoryCard = ({ kind = "main" }) => {
	const { data, isLoading, error, refetch } = useAvailabilityHistory(kind);
	const rows = data?.points ?? [];
	const option = useMemo(() => availabilityTrendOption(data?.points ?? []), [data]);

	const columns = [
		{ key: "week", label: "Week", render: (r) => formatDate(r.week) },
		{
			key: "availability_pct",
			label: "In stock",
			align: "right",
			render: (r) => pct(r.availability_pct),
		},
		{ key: "oos_pct", label: "Out of stock", align: "right", render: (r) => pct(r.oos_pct) },
		{
			key: "stores",
			label: "Stores",
			align: "right",
			render: (r) => formatNumber(r.stores),
		},
	];

	return (
		<ChartTableCard
			title="Availability trend (weekly)"
			isLoading={isLoading}
			error={error}
			refetch={refetch}
			isEmpty={rows.length === 0}
			emptyMessage="No availability history yet — it fills in as weekly scrapes accumulate."
			renderChart={() => <EChart option={option} height={280} />}
			columns={columns}
			rows={rows}
			rowKey={(r) => r.week}
		/>
	);
};
