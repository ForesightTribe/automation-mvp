import { useEffect, useMemo, useState } from "react";
import { Card } from "../../../components/ui/Card";
import { ChannelChips } from "../../../components/ui/ChannelChips";
import { InfoTooltip } from "../../../components/ui/InfoTooltip";
import { Pagination } from "../../../components/ui/Pagination";
import { ExportButton } from "../../../components/ui/ExportButton";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useDateRange } from "../../../context/DateRangeContext";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { chartColor } from "../../../lib/marketplaceColors";
import { marketplaceName } from "../../../lib/marketplace";
import { downloadCsv, exportName } from "../../../lib/exportTable";
import { formatNumber } from "../../../lib/format";
import { SortHead, TD, useClientSort } from "./insightsTable";
import { useSov, useZeptoSov } from "../hooks";

/** Marketplaces that report share of voice. Instamart does not. */
const REPORTING = ["blinkit", "zepto"];
const LIMIT = 20;
// Blinkit stores SOV as 0–100 (its API: 2.72, 100.0) — never rescaled. Two places under 1%.
const sovText = (v) =>
	v == null ? "—" : `${v.toFixed(v > 0 && v < 1 ? 2 : 1)}%`;

/** What a figure means, on hover. */
const ABOUT = {
	keyword: "The search term.",
	searches:
		"How often shoppers search this term in a month, as Blinkit reports it.",
	sov: "Your share of the sponsored visibility on this term (Blinkit) or campaign (Zepto).",
	campaign: "The Zepto campaign.",
	position:
		"Where the campaign's ads appeared on average. Lower is nearer the top.",
};

/**
 * Each marketplace's three summary tiles. The first is the overall reading and clears the
 * filter; the other two are filters on the table below.
 *
 * Blinkit: SOV weighted by monthly searches (a keyword nobody searches should not move the
 * headline), keywords you lead (SOV ≥ 50%), and big searches where you are weak — the top
 * quarter of keywords by searches with SOV under 10%, the clearest missed visibility.
 * Zepto has no searches, only campaigns and their ad position.
 */
const summaryFor = (platform, rows) => {
	if (platform === "blinkit") {
		const searches = rows.reduce(
			(s, r) => s + (r.monthly_searches ?? 0),
			0,
		);
		const weighted = searches
			? rows.reduce(
					(s, r) => s + (r.sov ?? 0) * (r.monthly_searches ?? 0),
					0,
				) / searches
			: rows.length
				? rows.reduce((s, r) => s + (r.sov ?? 0), 0) / rows.length
				: null;
		const sorted = [...rows]
			.map((r) => r.monthly_searches ?? 0)
			.sort((a, b) => a - b);
		const q3 = sorted.length ? sorted[Math.floor(sorted.length * 0.75)] : 0;
		const lead = (r) => (r.sov ?? 0) >= 50;
		const weak = (r) =>
			(r.monthly_searches ?? 0) >= q3 && (r.sov ?? 0) < 10;
		return [
			{
				key: "all",
				label: "Weighted SOV",
				value: sovText(weighted),
				note: "by monthly searches",
			},
			{
				key: "lead",
				label: "You lead",
				value: `${rows.filter(lead).length} keywords`,
				note: "SOV 50% or more",
				test: lead,
			},
			{
				key: "weak",
				label: "Big searches, weak",
				value: `${rows.filter(weak).length} keywords`,
				note: "top searches, SOV under 10%",
				test: weak,
				tone: "text-danger",
			},
		];
	}
	const avg = rows.length
		? rows.reduce((s, r) => s + (r.sov ?? 0), 0) / rows.length
		: null;
	const top = (r) => r.ad_position != null && r.ad_position <= 3;
	const low = (r) => r.ad_position != null && r.ad_position > 5;
	return [
		{
			key: "all",
			label: "Average SOV",
			value: sovText(avg),
			note: "across campaigns",
		},
		{
			key: "top",
			label: "Near the top",
			value: `${rows.filter(top).length} campaigns`,
			note: "ad position 1 to 3",
			test: top,
		},
		{
			key: "low",
			label: "Further down",
			value: `${rows.filter(low).length} campaigns`,
			note: "ad position below 5",
			test: low,
			tone: "text-danger",
		},
	];
};

/**
 * Share of voice — one card, a tab per marketplace that reports it (2026-10-08).
 *
 * Tabs rather than one table because the two are different measurements: Blinkit reports SOV
 * per KEYWORD, with its monthly searches, for the dates scraped; Zepto per CAMPAIGN, as a
 * trailing 7-day figure that ignores the picker (hence "as of"). Summary tiles on top answer
 * "how visible am I", and two of them filter the table. The table sorts, searches, pages and
 * exports like the Performance explorer. Blinkit's bars run on the true 0–100 scale; Zepto's
 * values are small, so its bars are relative to the top campaign.
 */
export const SovCard = () => {
	const { selected } = useMarketplaces();
	const { range } = useDateRange();
	const tabs = REPORTING.filter((m) => selected.includes(m));
	const [tab, setTab] = useState(null);
	const [filter, setFilter] = useState("all");
	const [query, setQuery] = useState("");
	const [page, setPage] = useState(1);
	const current = tabs.includes(tab) ? tab : tabs[0];
	const blinkit = useSov();
	const zepto = useZeptoSov();
	const q = current === "blinkit" ? blinkit : zepto;
	const isBlinkit = current === "blinkit";

	const all = useMemo(
		() =>
			(q.data ?? []).map((r) => ({
				...r,
				name: isBlinkit
					? r.keyword
					: (r.campaign_name ?? String(r.campaign_id)),
			})),
		[q.data, isBlinkit],
	);
	const tiles = useMemo(() => summaryFor(current, all), [current, all]);
	const active = tiles.find((t) => t.key === filter) ?? tiles[0];
	const filtered = useMemo(() => {
		const term = query.trim().toLowerCase();
		return all.filter(
			(r) =>
				(!active?.test || active.test(r)) &&
				(!term || r.name.toLowerCase().includes(term)),
		);
	}, [all, active, query]);
	const ACCESSORS = {
		name: (r) => r.name,
		// Zepto has no searches: a Blinkit sort carried over to its tab orders by SOV instead.
		searches: (r) => (isBlinkit ? r.monthly_searches : r.sov),
		position: (r) => r.ad_position,
		sov: (r) => r.sov,
	};
	const { sorted, sort, order, onSort } = useClientSort(
		filtered,
		ACCESSORS,
		isBlinkit ? "searches" : "sov",
	);
	useEffect(() => setPage(1), [current, filter, query, sort, order]);

	if (!tabs.length) return null;

	const pages = Math.max(1, Math.ceil(sorted.length / LIMIT));
	const visible = sorted.slice((page - 1) * LIMIT, page * LIMIT);
	const scale = isBlinkit
		? 100
		: Math.max(...all.map((r) => r.sov ?? 0), 0.0001);
	const asOf = !isBlinkit ? all[0]?.as_of : null;
	const head = (label, key, hint) => (
		<SortHead
			label={label}
			hint={hint}
			sortKey={key}
			sort={sort}
			order={order}
			onSort={onSort}
		/>
	);

	const onExport = () =>
		downloadCsv(exportName(`share-of-voice-${current}`, range), [
			{
				title: `Share of voice, ${marketplaceName(current)}${asOf ? `, as of ${asOf}` : `, ${range.from} to ${range.to}`}`,
				columns: [
					{
						header: isBlinkit ? "Keyword" : "Campaign",
						value: (r) => r.name,
					},
					isBlinkit
						? {
								header: "Monthly searches",
								value: (r) => r.monthly_searches ?? "",
							}
						: {
								header: "Ad position",
								value: (r) => r.ad_position ?? "",
							},
					{ header: "SOV %", value: (r) => r.sov ?? "" },
				],
				rows: sorted,
			},
		]);

	return (
		<Card
			title={
				<span className="inline-flex items-center gap-1.5">
					Share of voice
					<InfoTooltip label="How much of the sponsored visibility your ads took. Blinkit reports it per keyword, with how often the term is searched each month; Zepto per campaign, as a trailing 7-day figure that does not follow the date picker." />
				</span>
			}
			actions={
				asOf && (
					<span className="text-xs text-content-subtle">
						Trailing 7 days, as of {asOf}
					</span>
				)
			}
		>
			{/* Left-aligned, above the content: the same chips the Performance
			    Explorer uses, so one control means one thing across the page.
			    No "all" chip — share of voice is measured per marketplace and
			    the two scales are not comparable, so there is nothing to
			    combine. */}
			{tabs.length > 1 && (
				<div className="mb-3">
					<ChannelChips
						slugs={tabs}
						value={current}
						onSelect={(v) => {
							if (!v) return;
							setTab(v);
							setFilter("all");
							setQuery("");
						}}
					/>
				</div>
			)}
			{q.isLoading && <Loading label="Loading share of voice…" />}
			{q.error && (
				<ErrorState message={q.error.message} onRetry={q.refetch} />
			)}
			{!q.isLoading && !q.error && !all.length && (
				<EmptyState
					message={`No ${marketplaceName(current)} share of voice in this window.`}
				/>
			)}
			{!q.isLoading && !q.error && all.length > 0 && (
				<>
					<div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
						{tiles.map((t) => {
							const on = active?.key === t.key;
							return (
								<button
									key={t.key}
									type="button"
									aria-pressed={on}
									onClick={() =>
										setFilter(
											t.key === filter && t.test
												? "all"
												: t.key,
										)
									}
									className={`rounded-lg border px-3 py-2.5 text-left transition-colors ${
										on
											? "border-brand"
											: "border-border hover:border-content-subtle"
									}`}
								>
									<p className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
										{t.label}
									</p>
									<p
										className={`mt-1 font-display text-lg font-semibold ${t.tone && on ? t.tone : "text-content"}`}
									>
										{t.value}
									</p>
									<p className="text-xs text-content-muted">
										{t.note}
									</p>
								</button>
							);
						})}
					</div>

					<div className="mt-4 mb-2 flex flex-wrap items-center justify-between gap-2">
						<input
							type="search"
							value={query}
							onChange={(e) => setQuery(e.target.value)}
							placeholder={
								isBlinkit
									? "Search keywords"
									: "Search campaigns"
							}
							aria-label={
								isBlinkit
									? "Search keywords"
									: "Search campaigns"
							}
							className="w-52 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-content transition-colors focus:border-brand focus:outline-none"
						/>
						<ExportButton
							disabled={!sorted.length}
							onExport={onExport}
						/>
					</div>

					{!sorted.length ? (
						<EmptyState message="Nothing matches this filter." />
					) : (
						<>
							<div className="max-h-[70vh] overflow-auto rounded-lg border border-border">
								<table className="w-full border-collapse">
									<thead className="bg-card">
										<tr className="border-b border-border">
											<SortHead
												label={
													isBlinkit
														? "Keyword"
														: "Campaign"
												}
												hint={
													isBlinkit
														? ABOUT.keyword
														: ABOUT.campaign
												}
												sortKey="name"
												sort={sort}
												order={order}
												onSort={onSort}
											/>
											{isBlinkit
												? head(
														"Monthly searches",
														"searches",
														ABOUT.searches,
													)
												: head(
														"Ad position",
														"position",
														ABOUT.position,
													)}
											{head("SOV", "sov", ABOUT.sov)}
										</tr>
									</thead>
									<tbody>
										{visible.map((r) => (
											<tr
												key={
													isBlinkit
														? r.keyword
														: r.campaign_id
												}
												className="border-b border-border/60 last:border-0 hover:bg-muted"
											>
												<td
													className={`${TD} max-w-80 truncate font-medium`}
													title={r.name}
												>
													{r.name}
												</td>
												<td
													className={`${TD} text-center tabular-nums text-content-muted`}
												>
													{isBlinkit
														? formatNumber(
																r.monthly_searches,
															)
														: r.ad_position == null
															? "—"
															: r.ad_position.toFixed(
																	1,
																)}
												</td>
												<td className={`${TD} w-2/5`}>
													<span className="flex items-center gap-2.5">
														<span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
															<span
																className="block h-full rounded-full opacity-85"
																style={{
																	width: `${Math.min(100, ((r.sov ?? 0) / scale) * 100)}%`,
																	background:
																		chartColor(
																			current,
																		),
																}}
															/>
														</span>
														<span className="w-14 text-right tabular-nums">
															{sovText(r.sov)}
														</span>
													</span>
												</td>
											</tr>
										))}
									</tbody>
								</table>
							</div>
							<div className="mt-1">
								<Pagination
									page={page}
									pages={pages}
									total={sorted.length}
									limit={LIMIT}
									onChange={setPage}
								/>
							</div>
						</>
					)}
				</>
			)}
		</Card>
	);
};
