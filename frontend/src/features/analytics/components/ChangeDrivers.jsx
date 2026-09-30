import { useAnalyticsOverview } from "../hooks";
import { Loading } from "../../../components/feedback/Loading";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { formatCurrency, formatNumber } from "../../../lib/format";

/**
 * Why revenue moved: how much came from selling more, and how much from each
 * unit fetching more.
 *
 * The split is EXACT, not modelled. With p as revenue per unit and u as units:
 *
 *     volume = (u₁ − u₀) · p₀        price = (p₁ − p₀) · u₁
 *     volume + price = p₁u₁ − p₀u₀   — the whole change, nothing left over
 *
 * The two bars always reconcile to the total, with no residual. Volume is
 * valued at the old price and price at the new volume; the reverse split is
 * equally valid, so neither bar is presented as "the cause".
 *
 * ⚠️ Price here is revenue ÷ units, not a price the brand set — it moves with
 * the product MIX.
 */
const Bar = ({ value, scale, up }) => (
	<span
		aria-hidden
		className="relative block h-1.5 w-full overflow-hidden rounded-full bg-muted"
	>
		<span
			className={`absolute inset-y-0 left-0 rounded-full ${
				up ? "bg-info" : "bg-content-subtle"
			}`}
			style={{
				width: `${scale ? Math.max(2, (Math.abs(value) / scale) * 100) : 0}%`,
			}}
		/>
	</span>
);

const Driver = ({ label, value, scale, note }) => {
	const up = value >= 0;
	return (
		<div className="flex items-center gap-3 py-2">
			<span className="w-32 shrink-0 text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
				{label}
			</span>
			<span className="min-w-0 flex-1">
				<Bar value={value} scale={scale} up={up} />
			</span>
			<span className="w-28 shrink-0 text-right text-sm font-medium text-content tabular-nums">
				{up ? "+" : "−"}
				{formatCurrency(Math.abs(value))}
			</span>
			<span className="w-32 shrink-0 text-right text-[11px] text-content-muted tabular-nums">
				{note}
			</span>
		</div>
	);
};

const Total = ({ label, value }) => (
	<div className="flex items-baseline gap-3 py-2">
		<span className="flex-1 text-[11px] font-semibold tracking-wide text-content-subtle uppercase">
			{label}
		</span>
		<span className="w-28 text-right font-display text-base font-bold text-content tabular-nums">
			{formatCurrency(value)}
		</span>
		<span className="w-32 shrink-0" />
	</div>
);

export const ChangeDrivers = () => {
	const { data, isLoading } = useAnalyticsOverview();

	const v1 = data?.revenue?.value;
	const v0 = data?.revenue?.prev;
	const u1 = data?.units_sold?.value;
	const u0 = data?.units_sold?.prev;

	const ready =
		v1 != null &&
		v0 != null &&
		u1 != null &&
		u0 != null &&
		u0 > 0 &&
		u1 > 0;

	if (isLoading) {
		return (
			<section className="rounded-xl border border-border bg-card p-6">
				<Loading label="Loading drivers…" />
			</section>
		);
	}

	if (!ready) {
		return (
			<section className="rounded-xl border border-border bg-card p-6">
				<EmptyState message="Not enough history to split the change." />
			</section>
		);
	}

	const p0 = v0 / u0;
	const p1 = v1 / u1;
	const volume = (u1 - u0) * p0;
	const price = (p1 - p0) * u1;
	const scale = Math.max(Math.abs(volume), Math.abs(price));

	return (
		<section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
			<div className="flex flex-col gap-0.5">
				<h2 className="font-display text-base font-semibold text-content">
					What is driving the change
				</h2>
				<p className="text-xs text-content-muted">
					Revenue against the previous period of the same length,
					split into units sold and what each unit fetched.
				</p>
			</div>

			<div className="flex flex-col divide-y divide-border">
				<Total label="Previous period" value={v0} />
				<Driver
					label="From units"
					value={volume}
					scale={scale}
					note={`${formatNumber(u0)} → ${formatNumber(u1)}`}
				/>
				<Driver
					label="From revenue/unit"
					value={price}
					scale={scale}
					note={`₹${p0.toFixed(2)} → ₹${p1.toFixed(2)}`}
				/>
				<Total label="This period" value={v1} />
			</div>
		</section>
	);
};
