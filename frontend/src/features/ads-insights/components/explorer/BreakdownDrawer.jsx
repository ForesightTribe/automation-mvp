import { Drawer } from "../../../../components/ui/Drawer";
import { Stat, Section } from "../../../../components/ui/Stat";
import { formatCurrency, formatNumber } from "../../../../lib/format";
import { marketplaceName } from "../../../../lib/marketplace";
import { useDataWindow } from "../../hooks";
import { MarketplaceTag, MiniTable } from "../insightsTable";
import { DIM_LABEL } from "./explorerModel";
import { RoasPill } from "./explorerColumns";

const dash = "—";
const pct = (v, d = 1) => (v == null ? dash : `${v.toFixed(d)}%`);

/** A headed list: name (with its marketplace), spend, sales, RoAS. */
const SpendList = ({ items, nameLabel }) => (
	<MiniTable
		head={[
			{ label: nameLabel },
			{ label: "Spend", align: "right" },
			{ label: "Sales", align: "right" },
			{ label: "RoAS", align: "right" },
		]}
		rows={items.map((x) => ({
			key: x.key,
			cells: [
				<span key="n" className="flex min-w-0 items-center gap-1.5">
					{x.platform && <MarketplaceTag slug={x.platform} compact />}
					<span className="truncate text-content" title={x.name}>
						{x.name}
					</span>
				</span>,
				formatCurrency(x.spend),
				formatCurrency(x.sales),
				<RoasPill key="r" value={x.spend ? x.sales / x.spend : null} />,
			],
		}))}
	/>
);

/**
 * One product, retail category or city in full, opened from the Performance explorer.
 *
 * What the data holds for it, and nothing invented: its figures, its split by marketplace,
 * the campaigns its total is made of where the marketplace reports that (Instamart products),
 * and for a category, the advertised products in it.
 *
 * Same rules as the keyword drawer: a figure none of the row's marketplaces report is left
 * out, one only some report says who and is computed over those alone (explorerModel.figures).
 */
export const BreakdownDrawer = ({ row, dim, products = [], open, onClose }) => {
	const data = useDataWindow();
	if (!open || !row) return null;

	const reporters = (field) =>
		row.platforms.filter((p) =>
			row.members.some((m) => m.platform === p && m[field] != null),
		);
	const has = (field) => reporters(field).length > 0;
	const label = (name, field) => {
		const who = reporters(field);
		return who.length < row.platforms.length
			? `${name} · ${who.map(marketplaceName).join(", ")} only`
			: name;
	};

	const byMp = row.kids?.length
		? row.kids.map((k) => ({
				key: k.key,
				name: marketplaceName(k.platforms[0]),
				platform: k.platforms[0],
				spend: k.spend,
				sales: k.sales,
			}))
		: [
				{
					key: row.key,
					name: marketplaceName(row.platforms[0]),
					platform: row.platforms[0],
					spend: row.spend,
					sales: row.sales,
				},
			];
	const campaigns = row.members
		.flatMap((m) =>
			(m.campaigns ?? []).map((c) => ({ ...c, platform: m.platform })),
		)
		.sort((a, b) => b.spend - a.spend)
		.map((c) => ({
			key: `${c.platform}:${c.campaign_id}`,
			name: c.campaign_name ?? String(c.campaign_id),
			platform: c.platform,
			spend: c.spend,
			sales: c.sales,
		}));
	const inCategory =
		dim === "category"
			? products
					.filter(
						(p) =>
							(p.detail ?? "").toLowerCase() ===
								row.name.toLowerCase() &&
							row.platforms.includes(p.platform),
					)
					.sort((a, b) => b.spend - a.spend)
					.map((p) => ({
						key: `${p.platform}:${p.key}`,
						name: p.name,
						platform: p.platform,
						spend: p.spend,
						sales: p.sales,
					}))
			: [];

	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={row.name}
			subtitle={`${DIM_LABEL[dim]} · ${row.platforms.map(marketplaceName).join(" · ")}${row.sub ? ` · ${row.sub}` : ""}`}
			stats={
				<>
					<Stat label="Spend" value={formatCurrency(row.spend)} />
					<Stat label="Sales" value={formatCurrency(row.sales)} />
					<Stat
						label="RoAS"
						value={
							row.roas == null ? dash : `${row.roas.toFixed(2)}x`
						}
					/>
				</>
			}
		>
			<Section
				title="Performance"
				hint={`${data.from} to ${data.to} · ${data.days} days${data.partial ? " with data" : ""}`}
			>
				<dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
					{[
						["ACoS", pct(row.acos)],
						["Impressions", formatNumber(row.impressions)],
						[
							"CPM",
							row.cpm == null ? dash : formatCurrency(row.cpm),
						],
						...(has("clicks")
							? [
									[
										label("Clicks", "clicks"),
										formatNumber(row.clicks),
									],
									[label("CTR", "clicks"), pct(row.ctr, 2)],
									[
										label("CPC", "clicks"),
										row.cpc == null
											? dash
											: formatCurrency(row.cpc),
									],
								]
							: []),
						...(has("atc")
							? [
									[
										label("Add to cart", "atc"),
										formatNumber(row.atc),
									],
								]
							: []),
						...(has("units_sold")
							? [
									[
										label("Orders", "units_sold"),
										formatNumber(row.orders),
									],
									[
										label("Cost per order", "units_sold"),
										row.cpo == null
											? dash
											: formatCurrency(row.cpo),
									],
								]
							: []),
						...(has("units_sold") && has("clicks")
							? [["Conversion", pct(row.conv)]]
							: []),
					].map(([k, v]) => (
						<div
							key={k}
							className="flex justify-between gap-3 border-b border-border/60 py-1"
						>
							<dt className="text-content-muted">{k}</dt>
							<dd className="tabular-nums text-content">{v}</dd>
						</div>
					))}
				</dl>
			</Section>
			<Section title="By marketplace">
				<SpendList nameLabel="Marketplace" items={byMp} />
			</Section>
			{campaigns.length > 0 && (
				<Section
					title="By campaign"
					hint={`${campaigns.length} campaign${campaigns.length === 1 ? "" : "s"}`}
				>
					<SpendList nameLabel="Campaign" items={campaigns} />
				</Section>
			)}
			{dim === "category" && (
				<Section title="Advertised products in this category">
					{inCategory.length ? (
						<SpendList nameLabel="Product" items={inCategory} />
					) : (
						<p className="text-sm text-content-muted">
							No advertised products in this category in this
							window.
						</p>
					)}
				</Section>
			)}
		</Drawer>
	);
};
