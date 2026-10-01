import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { usePoSummary, usePoByMarketplace } from "../hooks";
import { ChannelSplit } from "./ChannelSplit";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatNumber } from "../../../lib/format";

/**
 * What the marketplace ordered over the window, and how much of it arrived.
 *
 * Fill rate is shown in percentage points rather than as a relative change: a
 * rate moving 93% to 96% is three points, and reporting it as 3.5% invites it to
 * be read as a share of the orders.
 */
const Delta = ({ value, unit = "percent", invert = false }) => {
	if (value === null || value === undefined)
		return <span className="text-content-subtle">—</span>;
	const flat = Math.round(value * 10) === 0;
	// `invert` is for measures where down is the good direction — missed value
	// falling is the supplier filling more, not less.
	const good = invert ? value < 0 : value > 0;
	const tone = flat
		? "text-content-muted"
		: good
			? "text-success"
			: "text-danger";
	return (
		<span className={`font-medium ${tone}`}>
			{value > 0 ? "▲" : "▼"}{" "}
			{unit === "pp"
				? `${Math.abs(value).toFixed(1)} pts`
				: `${Math.abs(value).toFixed(0)}%`}
		</span>
	);
};

const Row = ({ label, value, delta, unit, note, valueTone, invert }) => (
	<div className="flex items-baseline gap-3 border-b border-border py-2 last:border-0">
		<span className="flex-1 text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
			{label}
		</span>
		<span
			className={`w-28 text-right font-display text-base font-bold tabular-nums ${
				valueTone ?? "text-content"
			}`}
		>
			{value}
		</span>
		<span className="w-16 text-right text-[11px] tabular-nums">
			{delta === undefined ? null : (
				<Delta value={delta} unit={unit} invert={invert} />
			)}
		</span>
		<span className="w-36 text-[11px] text-content-subtle">{note}</span>
	</div>
);

export const PoPanel = () => {
	const { data, isLoading, error, refetch } = usePoSummary();
	const { data: byChannel, isPending: channelsPending } =
		usePoByMarketplace();

	// ⚠️ `usePoSummary` reads BLINKIT when no marketplace is named, so it
	// answers ₹0 for a tenant whose POs are on Instamart or Zepto. The headline
	// is totalled from the per-marketplace rows, which cover every channel.
	const rows = byChannel ?? [];

	// ⚠️ A purchase order is raised BY a marketplace. Its value, its fill rate
	// and its delivery cycle all belong to that one channel, so nothing here is
	// added across them — with several channels in view the table below is the
	// answer and there is no single figure above it. With one, that channel's
	// own figures are the account's.
	const single = rows.length === 1 ? rows[0] : null;
	const all = single
		? {
				po_value: single.po_value?.value ?? 0,
				value_at_risk: single.value_at_risk,
				value_missed: single.value_missed,
				open_pos: single.open_pos,
				closed_pos: single.closed_pos,
				// The rows carry a rate in points; this block reads a fraction.
				fill_rate:
					single.fill_rate?.value == null
						? null
						: single.fill_rate.value / 100,
				prev_fill_rate:
					single.fill_rate?.prev == null
						? null
						: single.fill_rate.prev / 100,
			}
		: rows.length
			? null
			: data;

	// Nothing is known about delivery until a PO closes. With none closed, a
	// missed value of zero is an absence of evidence, not a perfect record — an
	// open PO can still come up short — so both judged figures read as unknown
	// rather than as a clean sheet.
	const judged = (all?.closed_pos ?? 0) > 0;

	// A fill rate is a share, so its change belongs in points.
	const fillPp =
		all?.fill_rate != null && all?.prev_fill_rate != null
			? (all.fill_rate - all.prev_fill_rate) * 100
			: null;

	return (
		<section className="flex flex-col">
			<div className="flex flex-col gap-5 rounded-xl border border-border bg-card p-6">
				{isLoading && <Loading label="Loading purchase orders…" />}
				{error && (
					<ErrorState message={error.message} onRetry={refetch} />
				)}
				{!isLoading && !error && !data && (
					<EmptyState message="No purchase orders in this period." />
				)}

				{data && (
					<>
						<div className="grid grid-cols-1 gap-8 lg:grid-cols-5">
							<div className="flex flex-col gap-4 lg:col-span-2">
								<p className="text-[11px] font-semibold tracking-wide text-content-subtle">
									Purchase Orders
								</p>
								{/* Only one channel's own figure is ever shown
								    here; several are read per row below. */}
								{all && (
									<p className="font-display text-3xl font-bold text-content tabular-nums">
										{formatCurrency(all.po_value)}
									</p>
								)}
							</div>

							{/* Only where there is no channel breakdown below to
							    carry these per channel. */}
							{!channelsPending && rows.length < 2 && (
								<div className="flex flex-col lg:col-span-3">
									<Row
										label="Fill rate"
										value={
											judged && all?.fill_rate != null
												? `${(all.fill_rate * 100).toFixed(1)}%`
												: "—"
										}
										delta={judged ? fillPp : undefined}
										unit="pp"
										note={
											judged
												? undefined
												: "no POs closed in this window yet"
										}
									/>
									{/* No comparison: this counts what is open right now,
								    and an older window's figure decays to nothing as
								    its POs close. */}
									<Row
										label="Open and not yet delivered"
										value={formatCurrency(
											all?.value_at_risk,
										)}
									/>
									{(data?.open_states ?? []).map((st) => (
										<div
											key={st.state}
											className="flex items-baseline gap-3 border-b border-border py-1.5 pl-4 last:border-0"
										>
											<span className="flex-1 text-[11px] text-content-muted">
												{st.state === "Unscheduled"
													? "No delivery slot booked"
													: st.state}
												{st.overdue > 0 &&
													` · ${st.overdue} past expiry`}
											</span>
											<span className="w-28 text-right text-sm text-content-muted tabular-nums">
												{formatCurrency(st.value)}
											</span>
											<span className="w-16 text-right text-[11px] text-content-subtle tabular-nums">
												{formatNumber(st.pos)} POs
											</span>
											<span className="w-36" />
										</div>
									))}
									<Row
										label="Missed"
										invert
										value={
											judged
												? formatCurrency(
														all?.value_missed,
													)
												: "—"
										}
										delta={
											!judged ||
											rows.length > 0 ||
											data?.value_missed_delta == null
												? undefined
												: data.value_missed_delta * 100
										}
										note={
											judged
												? undefined
												: "nothing has closed yet"
										}
									/>
								</div>
							)}
						</div>

						{/* Every channel's purchase orders side by side: the
						    figures above are these added up. */}
						<ChannelSplit
							rows={rows}
							metric="po_value"
							label="PO value"
							showShare={false}
							wide
							extras={[
								{
									label: "Fill rate",
									width: "w-20",
									value: (m) =>
										m.fill_rate?.value == null
											? "—"
											: `${m.fill_rate.value.toFixed(1)}%`,
								},
								{
									label: "Open POs",
									width: "w-20",
									value: (m) => formatNumber(m.open_pos),
								},
								{
									label: "Open value",
									width: "w-28",
									value: (m) =>
										formatCurrency(m.value_at_risk),
								},
								{
									label: "Closed POs",
									width: "w-24",
									value: (m) => formatNumber(m.closed_pos),
								},
								{
									label: "Missed",
									width: "w-28",
									value: (m) =>
										formatCurrency(m.value_missed),
								},
							]}
						/>
						<Link
							to="/purchase-orders"
							className="mt-1 flex items-center justify-end gap-1 border-t border-border pt-3 text-xs font-medium text-brand hover:underline"
						>
							See all purchase orders
							<ArrowRight size={12} aria-hidden />
						</Link>
					</>
				)}
			</div>
		</section>
	);
};
