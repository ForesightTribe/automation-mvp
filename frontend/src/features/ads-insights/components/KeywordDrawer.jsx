import { useMemo } from "react";
import { Drawer } from "../../../components/ui/Drawer";
import { Stat, Section } from "../../../components/ui/Stat";
import { enumLabel, MarketplaceTag, MiniTable } from "./insightsTable";
import { campaignKey, useAllCampaigns } from "../hooks";
import { marketplaceName } from "../../../lib/marketplace";
import { formatCurrency, formatDate, formatNumber } from "../../../lib/format";
import { figures } from "./explorer/explorerModel";
import { RoasPill } from "./explorer/explorerColumns";

const dash = "—";
const pct = (v, d = 1) => (v == null ? dash : `${v.toFixed(d)}%`);

const sum = (rows, pick) => {
	let n = null;
	for (const r of rows) if (pick(r) != null) n = (n ?? 0) + pick(r);
	return n;
};

const Rows = ({ pairs }) => (
	<dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
		{pairs.map(([k, v]) => (
			<div
				key={k}
				className="flex justify-between gap-3 border-b border-border/60 py-1"
			>
				<dt className="text-content-muted">{k}</dt>
				<dd className="tabular-nums text-content">{v}</dd>
			</div>
		))}
	</dl>
);

/**
 * Two parts of one total as one thin bar, figures beside it. Blinkit splits SALES into direct
 * (the advertised product) and indirect (the brand's others in the basket); Zepto splits
 * ORDERS into direct (same SKU) and halo (another of the brand's) — a different measure, so
 * each is named for what it is.
 */
const SplitBar = ({ a, b, labelA, labelB, format }) => {
	const total = (a ?? 0) + (b ?? 0);
	if (!total)
		return (
			<p className="text-sm text-content-muted">
				Nothing attributed in this period.
			</p>
		);
	return (
		<>
			<div className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-muted">
				<span
					className="block bg-brand opacity-80"
					style={{ width: `${(a / total) * 100}%` }}
				/>
				<span
					className="block bg-brand-soft"
					style={{ width: `${(b / total) * 100}%` }}
				/>
			</div>
			<div className="mt-2 flex justify-between text-sm">
				<span className="text-content">
					{labelA} {format(a)}{" "}
					<span className="text-content-subtle tabular-nums">
						{pct((a / total) * 100)}
					</span>
				</span>
				<span className="text-content-muted">
					{labelB} {format(b)}{" "}
					<span className="text-content-subtle tabular-nums">
						{pct((b / total) * 100)}
					</span>
				</span>
			</div>
		</>
	);
};

/**
 * One keyword in full, opened from the Performance explorer: on one marketplace, or across
 * several when the explorer combines them. `row.members` are its campaign × keyword rows.
 *
 * The header totals every campaign that bids on it; the sections break it out by marketplace,
 * by each marketplace's own attribution split, and by campaign. Blinkit's figures are its
 * 8-day snapshot (labelled with its dates); Zepto's and Instamart's cover the selected dates.
 *
 * Read-only. Acting on a keyword belongs in Ad Automation.
 */
export const KeywordDrawer = ({ row, periods = [], open, onClose }) => {
	const members = useMemo(() => row?.members ?? [], [row]);
	const { items: campaigns } = useAllCampaigns();
	const nameOf = useMemo(() => {
		const by = new Map(campaigns.map((c) => [campaignKey(c), c.name]));
		return (r) => by.get(campaignKey(r)) ?? String(r.campaign_id);
	}, [campaigns]);

	if (!open || !row) return null;

	const platforms = row.platforms;
	const byMp = platforms.map((p) => {
		const rows = members.filter((m) => m.platform === p);
		return { platform: p, rows, ...figures(rows) };
	});
	const matches = [
		...new Set(members.map((m) => m.match_type).filter(Boolean)),
	];
	const campaignsN = new Set(
		members.map((m) => `${m.platform}:${m.campaign_id}`),
	).size;
	// Who reports a figure, among THIS keyword's marketplaces. A figure none of them report
	// is left out (a Blinkit keyword has no clicks row of dashes); one only some report is
	// labelled with who, and is computed over those alone (`figures` rebuilds ratios that way),
	// so a combined keyword's CTR never reads as clicks over everyone's impressions.
	const reporters = (field) =>
		platforms.filter((p) =>
			members.some((m) => m.platform === p && m[field] != null),
		);
	const label = (name, field) => {
		const who = reporters(field);
		return who.length && who.length < platforms.length
			? `${name} · ${who.map(marketplaceName).join(", ")} only`
			: name;
	};
	const has = (field) => reporters(field).length > 0;
	const periodOf = (slug) => {
		const p = periods.find((x) => x.platform === slug);
		if (!p?.end) return dash;
		return `${formatDate(p.start)} – ${formatDate(p.end)}${p.snapshot ? " (8-day total)" : ""}`;
	};
	return (
		<Drawer
			open={open}
			onClose={onClose}
			title={row.name}
			subtitle={`${platforms.map(marketplaceName).join(" · ")} · ${campaignsN} campaign${campaignsN === 1 ? "" : "s"}${
				matches.length ? ` · ${matches.map(enumLabel).join(", ")}` : ""
			}`}
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
				hint={platforms.length > 1 ? "" : periodOf(platforms[0])}
			>
				<Rows
					pairs={[
						["ACoS", pct(row.acos)],
						["Impressions", formatNumber(row.impressions)],
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
						...(has("orders")
							? [
									[
										label("Orders", "orders"),
										formatNumber(row.orders),
									],
								]
							: []),
						...(has("position")
							? [
									[
										label("Best position seen", "position"),
										`#${row.position}`,
									],
								]
							: []),
					]}
				/>
			</Section>

			{/* Always shown, one row per marketplace — with its own period, because Blinkit's
			    figures are an 8-day total and the others follow the picker. */}
			<Section title="By marketplace">
				<MiniTable
					head={[
						{ label: "Marketplace" },
						{ label: "Period" },
						{ label: "Spend", align: "right" },
						{ label: "Sales", align: "right" },
						{ label: "RoAS", align: "right" },
					]}
					rows={byMp.map((m) => ({
						key: m.platform,
						cells: [
							<MarketplaceTag key="mp" slug={m.platform} />,
							<span
								key="p"
								className="text-xs text-content-muted"
							>
								{periodOf(m.platform)}
							</span>,
							formatCurrency(m.spend),
							formatCurrency(m.sales),
							<RoasPill key="r" value={m.roas} />,
						],
					}))}
				/>
			</Section>

			{byMp.map((m) =>
				m.platform === "blinkit" ? (
					<Section
						key={`split-${m.platform}`}
						title={`${marketplaceName(m.platform)} · direct against indirect sales`}
						hint="what the ad sold, and what it sold alongside"
					>
						<SplitBar
							a={sum(m.rows, (r) => r.direct_sales)}
							b={sum(m.rows, (r) => r.indirect_sales)}
							labelA="Direct"
							labelB="Indirect"
							format={formatCurrency}
						/>
					</Section>
				) : m.platform === "zepto" &&
				  sum(m.rows, (r) => r.direct_orders) != null ? (
					<Section
						key={`split-${m.platform}`}
						title={`${marketplaceName(m.platform)} · direct against halo orders`}
						hint="the advertised product, and the brand's others"
					>
						<SplitBar
							a={sum(m.rows, (r) => r.direct_orders)}
							b={sum(m.rows, (r) => r.halo_orders)}
							labelA="Direct"
							labelB="Halo"
							format={formatNumber}
						/>
					</Section>
				) : null,
			)}

			<Section
				title="By campaign"
				hint={`${members.length} row${members.length === 1 ? "" : "s"}`}
			>
				<MiniTable
					head={[
						{ label: "Campaign" },
						...(has("match_type") ? [{ label: "Match" }] : []),
						{ label: "Spend", align: "right" },
						{ label: "Sales", align: "right" },
						{ label: "RoAS", align: "right" },
					]}
					rows={[...members]
						.sort((a, b) => (b.spend ?? 0) - (a.spend ?? 0))
						.map((r, i) => ({
							key: `${r.platform}-${r.campaign_id}-${r.match_type ?? ""}-${i}`,
							cells: [
								<span
									key="c"
									className="flex min-w-0 items-center gap-1.5"
								>
									<MarketplaceTag slug={r.platform} compact />
									<span
										className="truncate text-content"
										title={nameOf(r)}
									>
										{nameOf(r)}
									</span>
								</span>,
								...(has("match_type")
									? [
											<span
												key="m"
												className="text-content-muted"
											>
												{r.match_type
													? enumLabel(r.match_type)
													: dash}
											</span>,
										]
									: []),
								formatCurrency(r.spend ?? 0),
								formatCurrency(r.sales ?? 0),
								<RoasPill
									key="r"
									value={r.spend ? r.sales / r.spend : null}
								/>,
							],
						}))}
				/>
			</Section>
		</Drawer>
	);
};
