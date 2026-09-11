import { Drawer } from "../../../components/ui/Drawer";
import { Stat, Section } from "../../../components/ui/Stat";
import { Button } from "../../../components/ui/Button";
import { Loading } from "../../../components/feedback/Loading";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { CampaignStatusBadge } from "../../../components/ui/CampaignStatusBadge";
import { DataTable } from "../../../components/ui/DataTable";
import { Toggle } from "../../../components/ui/Toggle";
import { IndianRupee } from "lucide-react";
import {
	formatCurrency,
	formatNumber,
	formatPercent,
} from "../../../lib/format";
import { useCampaignTargets } from "../hooks";

/**
 * Everything the account knows about one campaign, with the page's three operations
 * attached to it.
 *
 * The controls repeat here on purpose. A drawer is where someone decides whether a
 * campaign needs changing, and sending them back to hunt for the right row afterwards is
 * how the wrong row gets clicked. They open the same confirmation the table does, so
 * there is still exactly one path to a live write.
 */
const TITLE_CASE = (s) =>
	(s ?? "")
		.toLowerCase()
		.split("_")
		.filter(Boolean)
		.map((w) => w.charAt(0).toUpperCase() + w.slice(1))
		.join(" ");

export const CampaignDrawer = ({ open, campaign, onClose, onAct, canAct }) => {
	const { data: targets, isLoading } = useCampaignTargets(
		open ? campaign?.campaign_id : null,
	);

	if (!campaign) return null;

	const spend = campaign.budget_consumed ?? 0;
	const sales = campaign.ad_sales ?? 0;
	// ACoS is the inverse of ROAS and the number most people actually budget against, so
	// it is derived here rather than leaving the reader to do it.
	const acos = sales > 0 ? (spend / sales) * 100 : null;
	const live = ["active", "running"].includes(
		(campaign.status ?? "").toLowerCase(),
	);

	const columns = [
		{
			key: "target",
			label: "Target",
			render: (t) => (
				<div className="min-w-0">
					<div className="truncate text-content" title={t.target}>
						{t.target || "—"}
					</div>
					<div className="text-[11px] text-content-subtle">
						{TITLE_CASE(t.target_type)}
						{t.match_type ? ` · ${TITLE_CASE(t.match_type)}` : ""}
					</div>
				</div>
			),
		},
		{
			key: "most_viewed_position",
			label: "Position",
			align: "right",
			render: (t) =>
				t.most_viewed_position ? (
					<span className="tabular-nums text-content">
						{t.most_viewed_position}
					</span>
				) : (
					<span className="text-content-subtle">—</span>
				),
		},
		{
			key: "budget_consumed",
			label: "Spend",
			align: "right",
			render: (t) => formatCurrency(t.budget_consumed ?? 0),
		},
		{
			key: "impressions",
			label: "Impressions",
			align: "right",
			render: (t) => formatNumber(t.impressions ?? 0),
		},
		{
			key: "total_roas",
			label: "ROAS",
			align: "right",
			render: (t) => (t.total_roas ? `${t.total_roas.toFixed(2)}x` : "—"),
		},
	];

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={campaign.name || `Campaign ${campaign.campaign_id}`}
			subtitle={`ID ${campaign.campaign_id} · ${TITLE_CASE(campaign.type)}`}
		>
			<div className="mb-5 flex flex-wrap items-center gap-3">
				<CampaignStatusBadge status={campaign.status} />
				<div className="flex flex-wrap gap-2">
					<Button
						size="xs"
						variant="secondary"
						onClick={() => onAct("budget", campaign)}
					>
						<IndianRupee size={12} /> Set budget
					</Button>
					<div className="flex items-center gap-2">
						<Toggle
							on={live}
							disabled={!canAct(campaign)}
							aria-label={
								live
									? "Stop this campaign"
									: "Start this campaign"
							}
							title={
								live
									? "Stop this campaign now"
									: "Start this campaign now"
							}
							onChange={() =>
								onAct(live ? "stop" : "start", campaign)
							}
						/>
						<span className="text-xs text-content-muted">
							{live ? "Running" : "Not running"}
						</span>
					</div>
				</div>
			</div>

			<Section title="Performance" hint="Over the selected window">
				<div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
					<Stat
						label="Daily budget"
						value={
							campaign.daily_budget
								? formatCurrency(campaign.daily_budget)
								: "Not set"
						}
					/>
					<Stat label="Spend" value={formatCurrency(spend)} />
					<Stat label="Ad sales" value={formatCurrency(sales)} />
					<Stat
						label="ROAS"
						value={
							campaign.roas ? `${campaign.roas.toFixed(2)}x` : "—"
						}
					/>
					<Stat
						label="ACoS"
						value={acos == null ? "—" : formatPercent(acos, 1)}
					/>
					<Stat
						label="Impressions"
						value={formatNumber(campaign.impressions ?? 0)}
					/>
					<Stat
						label="Adds to cart"
						value={formatNumber(campaign.atc ?? 0)}
					/>
					<Stat
						label="Units sold"
						value={formatNumber(campaign.quantities_sold ?? 0)}
					/>
				</div>
			</Section>

			<Section
				title="Targets"
				hint={targets?.length ? `${targets.length} shown` : null}
			>
				{isLoading && <Loading label="Loading targets…" />}
				{!isLoading && !targets?.length && (
					<EmptyState
						title="No targets"
						message="Nothing was recorded for this campaign in the selected window."
					/>
				)}
				{!isLoading && targets?.length > 0 && (
					<div className="overflow-hidden rounded-lg border border-border">
						<DataTable
							columns={columns}
							rows={targets}
							rowKey={(t, i) => `${t.target}-${i}`}
							maxHeight={340}
							minWidth={620}
							defaultSort="budget_consumed"
						/>
					</div>
				)}
			</Section>
		</Drawer>
	);
};
