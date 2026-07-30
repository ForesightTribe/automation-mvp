import { useState } from "react";
import { Button } from "../../../components/ui/Button";
import { useCampaignKeywords, useCreateBidRule } from "../hooks";
import { CampaignPicker } from "./CampaignPicker";
import { TimingFields, emptyTiming, timingPayload } from "./TimingFields";

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
 * Automate a keyword's bid: chase a target search position within a ₹ range, during
 * chosen times. Campaign is picked by name; the keyword field suggests keywords that
 * already exist on the chosen campaign. Position is measured at one store in the given
 * city, but the bid applies campaign-wide.
 */
export const AutomateBidForm = ({ onDone }) => {
	const [campaign, setCampaign] = useState({ id: "", name: "" });
	const [f, setF] = useState({
		keyword: "",
		target_position: "3",
		min_bid: "",
		max_bid: "",
		city: "",
		location_id: "",
	});
	const [timing, setTiming] = useState(emptyTiming());
	const mutation = useCreateBidRule();
	const { data: kwData } = useCampaignKeywords(campaign.id || null);
	const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

	const suggestions = (kwData ?? []).map((k) => k.keyword);
	const valid = campaign.id && f.keyword && f.min_bid && f.max_bid;

	const submit = (e) => {
		e.preventDefault();
		if (!valid) return;
		mutation.mutate(
			{
				campaign_id: Number(campaign.id),
				campaign_name: campaign.name || null,
				keyword: f.keyword,
				target_position: Number(f.target_position),
				min_bid: Number(f.min_bid),
				max_bid: Number(f.max_bid),
				city: f.city || undefined,
				location_id: f.location_id || undefined,
				...timingPayload(timing, { stop: true }),
			},
			{ onSuccess: () => onDone?.() },
		);
	};

	return (
		<form onSubmit={submit} className="space-y-4">
			<div className="grid gap-4 sm:grid-cols-2">
				<Field label="Campaign" className="sm:col-span-2">
					<CampaignPicker
						value={campaign.id}
						name={campaign.name}
						onChange={(id, name) => setCampaign({ id, name })}
					/>
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
				<Field label="Max bid (₹)">
					<input type="number" value={f.max_bid} onChange={set("max_bid")} placeholder="120" className={FIELD} />
				</Field>
				<Field label="Measure in city" hint="Position is checked at one store here.">
					<input value={f.city} onChange={set("city")} placeholder="bengaluru" className={FIELD} />
				</Field>
			</div>

			<Field
				label="Specific store (optional)"
				hint="A merchant/store id, if you want to measure at one store instead of any in the city."
				className="max-w-xs"
			>
				<input value={f.location_id} onChange={set("location_id")} placeholder="e.g. 31288" className={FIELD} />
			</Field>

			<div className="space-y-3 border-t border-border pt-4">
				<div>
					<h3 className="text-sm font-semibold text-content">When should it run?</h3>
					<p className="text-xs text-content-muted">The bid is only adjusted during this window.</p>
				</div>
				<TimingFields value={timing} onChange={setTiming} />
			</div>

			{mutation.isError && (
				<p className="text-xs text-danger">{mutation.error?.message ?? "Failed to create bid automation"}</p>
			)}

			<div className="flex gap-2">
				<Button type="submit" disabled={mutation.isPending || !valid}>
					{mutation.isPending ? "Creating…" : "Create bid automation"}
				</Button>
				<Button type="button" variant="ghost" onClick={onDone}>
					Cancel
				</Button>
			</div>
		</form>
	);
};
