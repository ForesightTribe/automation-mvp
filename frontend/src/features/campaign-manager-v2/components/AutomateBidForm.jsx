import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { useCampaignKeywords, useCreateBidRule, useUpdateBidRule } from "../hooks";
import { CampaignPicker } from "./CampaignPicker";
import { TimingFields, emptyTiming, timingFromRule, timingPayload } from "./TimingFields";

const FIELD =
	"rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-content focus:border-primary focus:outline-none";
const LABEL = "text-xs font-medium text-content-muted";

const Field = ({ label, hint, className = "", children }) => (
	<label className={`flex flex-col gap-1 ${className}`}>
		<span className={LABEL}>{label}</span>
		{children}
		{hint && <span className="text-xs text-content-subtle">{hint}</span>}
	</label>
);

/**
 * Create OR edit a keyword bid automation. Pass `editing` (a bid rule) to edit — the form
 * pre-fills and PATCHes; the campaign is fixed (identity, not editable). Otherwise it creates.
 */
export const AutomateBidForm = ({ editing = null, onDone }) => {
	const isEdit = Boolean(editing);
	const [campaign, setCampaign] = useState(
		isEdit ? { id: editing.campaign_id, name: editing.campaign_name } : { id: "", name: "" },
	);
	const [f, setF] = useState({
		keyword: editing?.keyword ?? "",
		target_position: String(editing?.target_position ?? "3"),
		min_bid: editing?.min_bid != null ? String(editing.min_bid) : "",
		max_bid: editing?.max_bid != null ? String(editing.max_bid) : "",
		city: "",
		location_id: "",
	});
	const [timing, setTiming] = useState(
		isEdit ? timingFromRule(editing, { stop: true }) : emptyTiming(),
	);
	const create = useCreateBidRule();
	const update = useUpdateBidRule();
	const mutation = isEdit ? update : create;
	const { data: kwData } = useCampaignKeywords(campaign.id || null);
	const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

	const suggestions = (kwData ?? []).map((k) => k.keyword);
	// Max bid is optional — blank means "reach the target position whatever it costs".
	// A measurement location is NOT optional: without one the engine silently falls back to
	// a default Bengaluru store, so every rule ends up measuring somewhere nobody chose.
	// On edit, a blank city is fine only when the rule already has a location to keep.
	const hasLocation = Boolean(f.city || f.location_id || (isEdit && editing?.location_name));
	const valid = campaign.id && f.keyword && f.min_bid && hasLocation;

	const submit = (e) => {
		e.preventDefault();
		if (!valid) return;
		const timed = timingPayload(timing, { stop: true });
		const common = {
			keyword: f.keyword,
			target_position: Number(f.target_position),
			min_bid: Number(f.min_bid),
			max_bid: f.max_bid === "" ? null : Number(f.max_bid),
			city: f.city || undefined,
			location_id: f.location_id || undefined,
			...timed,
		};
		if (isEdit) {
			update.mutate({ ruleId: editing.id, body: common }, { onSuccess: () => onDone?.() });
		} else {
			create.mutate(
				{ campaign_id: Number(campaign.id), campaign_name: campaign.name || null, ...common },
				{ onSuccess: () => onDone?.() },
			);
		}
	};

	return (
		<form onSubmit={submit} className="space-y-4">
			<div className="grid gap-4 sm:grid-cols-2">
				<Field label="Campaign" className="sm:col-span-2">
					{isEdit ? (
						<div className="rounded-md border border-border bg-muted px-2.5 py-1.5 text-sm text-content">
							{campaign.name || `campaign ${campaign.id}`}
							<span className="ml-1.5 text-xs text-content-subtle">#{campaign.id}</span>
						</div>
					) : (
						<CampaignPicker
							value={campaign.id}
							name={campaign.name}
							onChange={(id, name) => setCampaign({ id, name })}
						/>
					)}
				</Field>
				<Field
					label="Keyword"
					hint={campaign.id ? "Suggestions come from this campaign." : "Pick a campaign for suggestions."}
				>
					<input
						list="cm2-keyword-suggestions"
						value={f.keyword}
						onChange={set("keyword")}
						placeholder="goli soda"
						className={FIELD}
					/>
					<datalist id="cm2-keyword-suggestions">
						{suggestions.map((k) => (
							<option key={k} value={k} />
						))}
					</datalist>
				</Field>
				<Field label="Target position" hint="Where you want to rank (1 = top).">
					<input
						type="number"
						min="1"
						value={f.target_position}
						onChange={set("target_position")}
						className={FIELD}
					/>
				</Field>
			</div>

			<div className="grid gap-4 sm:grid-cols-3">
				<Field label="Min bid (₹)">
					<input type="number" value={f.min_bid} onChange={set("min_bid")} placeholder="20" className={FIELD} />
				</Field>
				<Field label="Max bid (₹)" hint="Optional — leave blank to chase the target position with no ceiling">
					<input type="number" value={f.max_bid} onChange={set("max_bid")} placeholder="No limit" className={FIELD} />
				</Field>
				<Field
					label="Measure in city *"
					hint={
						isEdit
							? editing?.location_name
								? `Currently: ${editing.location_name}. Enter a new city to change; leave blank to keep.`
								: "Required — this rule has no measurement store yet."
							: "Required — position is checked at one store here."
					}
				>
					<input
						value={f.city}
						onChange={set("city")}
						placeholder="bengaluru"
						className={FIELD}
						aria-invalid={!hasLocation}
					/>
				</Field>
			</div>

			<div className="space-y-3 border-t border-border pt-4">
				<div>
					<h3 className="text-sm font-semibold text-content">When should it run?</h3>
					<p className="text-xs text-content-muted">The bid is only adjusted during this window.</p>
				</div>
				<TimingFields value={timing} onChange={setTiming} />
			</div>

			{mutation.isError && (
				<p className="text-xs text-danger">
					{mutation.error?.message ?? `Failed to ${isEdit ? "save" : "create"} bid automation`}
				</p>
			)}

			<div className="flex gap-2">
				<Button type="submit" disabled={mutation.isPending || !valid}>
					{mutation.isPending ? "Saving…" : isEdit ? "Save changes" : "Create bid automation"}
				</Button>
				<Button type="button" variant="ghost" onClick={onDone}>
					Cancel
				</Button>
			</div>
		</form>
	);
};
