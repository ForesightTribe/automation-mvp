import { Target, MapPin, Clock, IndianRupee } from "lucide-react";
import { RuleTimingFields } from "./RuleTimingFields";
import { Combobox } from "./Combobox";
import { formatCurrency } from "../../../lib/format";

/**
 * The keyword automation's one action, given the same card treatment as a budget action.
 *
 * Card, icon chip, editable headline, sectioned body with eyebrows: the same anatomy as
 * ActionCards, so the keyword and campaign sides of one wizard read as one product rather
 * than two idioms. The fields are exactly what the engine takes; only their shape is shared.
 */
const INPUT =
	"rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-content transition-colors focus:border-brand focus:outline-none aria-[invalid=true]:border-danger";
const LABEL = "mb-1 block text-xs text-content-muted";
const EYEBROW =
	"flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-content-subtle";

const Section = ({ icon: Icon, title, children }) => (
	<div className="border-t border-border px-4 py-3.5">
		<p className={`${EYEBROW} mb-2.5`}>
			<Icon size={12} />
			{title}
		</p>
		{children}
	</div>
);

export const KeywordActionCard = ({
	keyword,
	targetPosition,
	onTargetPosition,
	minBid,
	onMinBid,
	maxBid,
	onMaxBid,
	belowFloor,
	effectiveFloor,
	floor,
	campaignFloor,
	scrapedAt,
	city,
	onCity,
	cityOptions,
	allCities = [],
	singleCity,
	hasLocation,
	existingLocationName,
	isEdit,
	timing,
	onTiming,
}) => (
	<div className="rounded-lg border border-border bg-card">
		{/* The headline states the action and carries the number that defines it, the way a
		    budget card carries its amount. */}
		<div className="flex flex-wrap items-center gap-2 px-4 py-3">
			<span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-brand">
				<Target size={14} />
			</span>
			<div className="flex flex-wrap items-baseline gap-1.5 font-display text-base font-semibold tracking-tight text-content">
				Hold rank
				<span className="inline-flex items-baseline rounded-md border border-border bg-card focus-within:border-brand">
					<span className="pl-2 text-sm font-normal text-content-muted">
						#
					</span>
					<input
						type="number"
						min="1"
						aria-label="Target position"
						value={targetPosition}
						onChange={(e) => onTargetPosition(e.target.value)}
						className="w-16 bg-transparent px-1 py-1 text-base font-semibold text-content tabular-nums focus:outline-none"
					/>
				</span>
				{keyword && (
					<span className="font-normal text-content-muted">
						for “{keyword}”
					</span>
				)}
			</div>
		</div>

		<Section icon={IndianRupee} title="Bid limits">
			<div className="flex flex-wrap gap-4">
				<div className="w-44">
					<label className={LABEL}>Min bid (₹)</label>
					<input
						type="number"
						value={minBid}
						aria-invalid={belowFloor}
						onChange={(e) => onMinBid(e.target.value)}
						className={`w-full ${INPUT}`}
					/>
				</div>
				<div className="w-44">
					<label className={LABEL}>
						Max bid{" "}
						<span className="text-content-subtle">(optional)</span>
					</label>
					<input
						type="number"
						value={maxBid}
						onChange={(e) => onMaxBid(e.target.value)}
						placeholder="No ceiling"
						className={`w-full ${INPUT}`}
					/>
				</div>
			</div>
			{belowFloor ? (
				<p className="mt-2 text-[11px] text-danger">
					Below Blinkit's minimum of {formatCurrency(effectiveFloor)}.
					It would be raised to {formatCurrency(effectiveFloor)} on
					the first write.
				</p>
			) : (
				<p className="mt-2 text-[11px] text-content-subtle">
					{floor?.min_bid != null
						? `Blinkit's minimum for “${keyword}” is ${formatCurrency(floor.min_bid)}${
								floor.suggested_min && floor.suggested_max
									? `. It suggests ${formatCurrency(floor.suggested_min)} to ${formatCurrency(floor.suggested_max)}`
									: ""
							}`
						: campaignFloor
							? `This campaign's published minimums run ${
									campaignFloor.single
										? formatCurrency(campaignFloor.lo)
										: `${formatCurrency(campaignFloor.lo)} to ${formatCurrency(campaignFloor.hi)}`
								}. Pick one of its keywords for the exact floor.`
							: keyword
								? scrapedAt
									? "No published minimum for this keyword yet. It syncs after the next daily scrape."
									: "This campaign hasn't been scraped yet; minimums sync nightly."
								: ""}
				</p>
			)}
		</Section>

		{/* Required. Without a city the engine falls back to a default Bengaluru store
		    silently, so the field is the only thing standing between a rule and a number
		    measured somewhere nobody chose. */}
		<Section icon={MapPin} title="Evaluation city">
			<div className="w-72">
				{cityOptions.length ? (
					<select
						value={city}
						onChange={(e) => onCity(e.target.value)}
						aria-invalid={!hasLocation}
						className={`w-full ${INPUT}`}
					>
						<option value="">Select a city…</option>
						{cityOptions.map((c) => (
							<option key={c.id} value={c.name} disabled={!c.lat}>
								{c.name}
								{c.lat ? "" : " (no dark store in our catalog)"}
							</option>
						))}
					</select>
				) : (
					<Combobox
						id="evaluation-city"
						value={city}
						onChange={onCity}
						invalid={!hasLocation}
						placeholder="Start typing a city"
						options={allCities.map((c) => ({
							value: c.slug,
							label: c.name,
							hint: c.state,
						}))}
					/>
				)}
				<p className="mt-1.5 text-[11px] text-content-subtle">
					{cityOptions.length
						? singleCity
							? `This campaign only targets ${singleCity.name}.${
									singleCity.location_name
										? ` Store: ${singleCity.location_name}.`
										: ""
								}`
							: "This campaign targets these cities. Pick where to measure."
						: isEdit && existingLocationName
							? `Currently: ${existingLocationName}. Enter a city to change it; leave blank to keep.`
							: ""}
				</p>
			</div>
		</Section>

		<Section icon={Clock} title="When to check">
			<RuleTimingFields value={timing} onChange={onTiming} />
		</Section>
	</div>
);
