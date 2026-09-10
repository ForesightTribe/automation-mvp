import { Target, Clock } from "lucide-react";
import { RuleTimingFields } from "./RuleTimingFields";
import { HoverHint } from "../../../components/ui/HoverHint";
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

const Section = ({ icon: Icon, title, bordered = true, children }) => (
	<div className={`px-4 py-3.5 ${bordered ? "border-t border-border" : ""}`}>
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
}) => {
	/**
	 * What Blinkit publishes as the floor for this keyword, carried on the label rather than
	 * printed under the field. It is guidance for the moment the number is typed, not a
	 * standing statement, and as a permanent paragraph it is the tallest thing in the card.
	 * The one case that stays on the page is `belowFloor`, because that is an error the
	 * reader has to act on.
	 */
	const floorHint =
		floor?.min_bid != null
			? `Blinkit's minimum for “${keyword}” is ${formatCurrency(floor.min_bid)}${
					floor.suggested_min && floor.suggested_max
						? `. It suggests ${formatCurrency(floor.suggested_min)} to ${formatCurrency(floor.suggested_max)}`
						: ""
				}.`
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
					: null;

	const cityNote = cityOptions.length
		? singleCity
			? `This campaign only targets ${singleCity.name}.${
					singleCity.location_name
						? ` Store: ${singleCity.location_name}.`
						: ""
				}`
			: "This campaign targets these cities. Pick where to measure."
		: isEdit && existingLocationName
			? `Currently: ${existingLocationName}. Enter a city to change it; leave blank to keep.`
			: null;

	return (
		<div className="rounded-lg border border-border bg-card">
			{/* This line IS the automation: everything below it is a constraint on how the
			    engine reaches this position. So it gets the weight — a filled brand mark and
			    larger, heavier type — while the sections below stay quiet.

			    ⚠️ The emphasis is SIZE, not colour. The figure is ink, and brand appears once,
			    on the mark. A big red number beside red validation copy competes with it, and
			    red on a form reads as something being wrong rather than something being
			    important. */}
			<div className="flex flex-wrap items-center gap-2.5 px-4 py-4">
				<span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-on-brand">
					<Target size={17} />
				</span>
				<div className="flex flex-wrap items-baseline gap-2 font-display text-lg font-semibold tracking-tight text-content">
					Target position
					<span className="inline-flex items-baseline rounded-md border-2 border-border bg-card transition-colors focus-within:border-brand">
						<span className="pl-2 text-base font-normal text-content-subtle">
							#
						</span>
						<input
							type="number"
							min="1"
							aria-label="Target position"
							value={targetPosition}
							onChange={(e) => onTargetPosition(e.target.value)}
							className="w-16 bg-transparent px-1 py-0.5 text-xl font-bold text-content tabular-nums focus:outline-none"
						/>
					</span>
					{/* The keyword carries equal weight to the number: this line says WHICH term
					    is being defended and at WHAT position, and either one alone is only half
					    the automation. Muted small text made the keyword read as a caption on
					    the number rather than as the other half of the same sentence. */}
					{keyword && (
						<>
							<span className="text-base font-normal text-content-muted">
								for
							</span>
							<span className="max-w-[22rem] truncate text-lg font-semibold text-content">
								&ldquo;{keyword}&rdquo;
							</span>
						</>
					)}
				</div>
			</div>

			{/* One row of three short fields, each carrying its own label. No section
			    eyebrows above them: heading-weight furniture around inputs that already
			    say what they are costs the card roughly twice its content in height. */}
			<div className="flex flex-wrap gap-4 border-t border-border px-4 py-3.5">
				<div className="w-40">
					<label className={LABEL}>
						<HoverHint label={floorHint}>
							<span
								className={
									floorHint
										? "cursor-help decoration-content-subtle/40 decoration-dotted underline-offset-4 hover:underline"
										: ""
								}
							>
								Min bid (₹)
							</span>
						</HoverHint>
					</label>
					<input
						type="number"
						value={minBid}
						aria-invalid={belowFloor}
						onChange={(e) => onMinBid(e.target.value)}
						className={`w-full ${INPUT}`}
					/>
				</div>

				<div className="w-40">
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

				{/* Required. Without a city the engine falls back to a default Bengaluru store
				    silently, so this field is the only thing standing between a rule and a
				    number measured somewhere nobody chose. */}
				<div className="w-64">
					<label className={LABEL}>Evaluation city</label>
					{cityOptions.length ? (
						<select
							value={city}
							onChange={(e) => onCity(e.target.value)}
							aria-invalid={!hasLocation}
							className={`w-full ${INPUT}`}
						>
							<option value="">Select a city…</option>
							{cityOptions.map((c) => (
								<option
									key={c.id}
									value={c.name}
									disabled={!c.lat}
								>
									{c.name}
									{c.lat
										? ""
										: " (no dark store in our catalog)"}
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
				</div>
			</div>

			{(belowFloor || cityNote) && (
				<div className="flex flex-col gap-1 px-4 pb-3 text-[11px]">
					{belowFloor && (
						<p className="text-danger">
							Below Blinkit&rsquo;s minimum of{" "}
							{formatCurrency(effectiveFloor)}. It would be raised
							to {formatCurrency(effectiveFloor)} on the first
							write.
						</p>
					)}
					{cityNote && (
						<p className="text-content-subtle">{cityNote}</p>
					)}
				</div>
			)}

			<Section icon={Clock} title="When to check">
				<RuleTimingFields value={timing} onChange={onTiming} />
			</Section>
		</div>
	);
};
