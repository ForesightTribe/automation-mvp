import { Fragment, useEffect, useState } from "react";
import { useFacilities } from "../hooks";
import { FacilityPos } from "./FacilityPos";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCompactCurrency, formatNumber } from "../../../lib/format";

const LIMIT = 20;

const formatPct = (v) =>
	v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`;

/** Facilities ranked by potential fill loss for the selected week. Each row
 * expands into the POs behind that facility's loss (the supply story) — fetched
 * lazily on expand. Server-paginated; resets to page 1 when the week changes. */
export const FacilitiesCard = ({ from }) => {
	const [page, setPage] = useState(1);
	const [expanded, setExpanded] = useState(null);
	useEffect(() => {
		setPage(1);
		setExpanded(null);
	}, [from]);

	const { data, isLoading, error, refetch, isFetching } = useFacilities({
		from,
		page,
		limit: LIMIT,
	});
	const rows = data?.items ?? [];

	const toggle = (id) => setExpanded((cur) => (cur === id ? null : id));

	return (
		<Card title="Facilities by fill loss">
			{isLoading && <Loading label="Loading facilities…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(rows.length === 0 ? (
					<EmptyState message="No facility data for this week." />
				) : (
					<div className={isFetching ? "opacity-60 transition-opacity" : ""}>
						<div className="overflow-auto">
							<table className="w-full border-collapse text-sm">
								<thead className="sticky top-0 z-10 bg-card">
									<tr className="border-b border-border text-content-subtle">
										<th className="w-8 px-3 py-2" />
										<th className="px-3 py-2 text-left font-medium">
											Facility
										</th>
										<th className="px-3 py-2 text-left font-medium">
											City
										</th>
										<th className="px-3 py-2 text-right font-medium">
											Fill rate
										</th>
										<th className="px-3 py-2 text-right font-medium">
											PO / GRN
										</th>
										<th className="px-3 py-2 text-right font-medium">
											Potential loss
										</th>
									</tr>
								</thead>
								<tbody>
									{rows.map((f) => {
										const open = expanded === f.facility_id;
										return (
											<Fragment key={f.facility_id}>
												<tr
													onClick={() => toggle(f.facility_id)}
													className="cursor-pointer border-b border-border/60 hover:bg-muted/50"
												>
													<td className="px-3 py-2 text-content-muted">
														{open ? "▾" : "▸"}
													</td>
													<td className="px-3 py-2 font-medium text-content">
														{f.facility_name ||
															`#${f.facility_id}`}
													</td>
													<td className="px-3 py-2 text-content-muted">
														{f.city_name || "—"}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{formatPct(f.fill_rate)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content-muted">
														{formatNumber(
															f.total_po_quantity,
														)}{" "}
														/{" "}
														{formatNumber(
															f.total_grn_quantity,
														)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{formatCompactCurrency(
															f.potential_loss,
														)}
													</td>
												</tr>
												{open && (
													<tr className="border-b border-border/60 bg-muted/30">
														<td
															colSpan={6}
															className="px-3 py-3"
														>
															<FacilityPos
																facilityId={
																	f.facility_id
																}
															/>
														</td>
													</tr>
												)}
											</Fragment>
										);
									})}
								</tbody>
							</table>
						</div>
						<Pagination
							page={data.page}
							pages={data.pages}
							total={data.total}
							limit={data.limit}
							onChange={setPage}
						/>
					</div>
				))}
		</Card>
	);
};
