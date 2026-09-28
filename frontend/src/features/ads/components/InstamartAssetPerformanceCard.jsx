import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useInstamartKeywords, useInstamartProducts } from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useDateRange } from "../../../context/DateRangeContext";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCurrency, formatNumber } from "../../../lib/format";
import { InstamartAssetDrawer } from "./InstamartAssetDrawer";

const LIMIT = 20;

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;
const formatPct = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}%`;

/** Only two breakdowns, unlike Zepto's four: Instamart's ad data has no
 * retail-category or city dimension anywhere (checked — nothing in any
 * captured response resembles one), so there is no honest Category/City
 * tab to add here. If that turns out to exist on a different endpoint,
 * this is the file to extend, mirroring ZeptoAssetPerformanceCard. */
const DIMENSIONS = [
	{ key: "all", label: "All" },
	{ key: "product", label: "Product" },
	{ key: "keyword", label: "Keyword" },
];

const TYPE_LABEL = { product: "Product", keyword: "Keyword" };

/** Instamart's product and keyword ad performance in one card, combined by
 * default — the same "union, not a sum" pattern as Zepto's equivalent card
 * (see its docstring): a product row and a keyword row can represent the
 * same spend counted twice, so the combined view is grouped sections ranked
 * independently, never a single summed total.
 *
 * Both breakdowns are account-wide totals — the same product or keyword can
 * be bid by more than one campaign, and these sum across all of them, exactly
 * like Zepto's product/keyword tables. The Campaign column additionally
 * attributes each row's total to the campaign(s) it came from (a count here,
 * same style as Blinkit's Keyword insights — the full per-campaign split is
 * one click away in the drawer, not spelled out in the table).
 *
 * No ad-type filter (Item/Banner/...): it existed earlier and was removed.
 * METRIC_FILTER_TYPE_CAMPAIGN_TYPE was verified live to work once, then
 * verified live to NOT discriminate between types at all after a session
 * re-login — real spend was triple-counted when the (now-removed) by-type
 * data was summed. Unreliable at the API level, so removed rather than
 * shipped on data that can't be trusted — see asset_metrics.py's docstring.
 *
 * `units_sold` is always 0: Instamart's ad data never reports a unit count
 * anywhere (checked both this endpoint and the campaign-level ones).
 */
export const InstamartAssetPerformanceCard = () => {
	const [dimension, setDimension] = useState("all");
	const [page, setPage] = useState(1);
	const [openRow, setOpenRow] = useState(null);
	const menuRef = useRef(null);

	const { selected } = useMarketplaces();
	const wantsInstamart = !selected?.length || selected.includes("instamart");
	const { range } = useDateRange();

	useEffect(() => {
		setPage(1);
	}, [dimension, selected]);

	const isAll = dimension === "all";
	const isProduct = dimension === "product";
	const isKeyword = dimension === "keyword";

	const products = useInstamartProducts({ enabled: isAll || isProduct });
	const keywords = useInstamartKeywords({ enabled: isAll || isKeyword });

	const sources = { product: products, keyword: keywords };
	const shown = isAll ? Object.keys(sources) : [dimension];

	const isLoading = shown.some((k) => sources[k].isLoading);
	const error = shown.map((k) => sources[k].error).find(Boolean) ?? null;
	const isFetching = shown.some((k) => sources[k].isFetching);
	const refetch = () => shown.forEach((k) => sources[k].refetch());

	const groups = useMemo(() => {
		return shown.map((key) => ({
			key,
			rows: [...(sources[key].data ?? [])]
				.sort((a, b) => (b.spend ?? 0) - (a.spend ?? 0))
				.map((r) => ({ ...r, _dim: key })),
		}));
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [products.data, keywords.data, dimension]);

	const total = groups.reduce((n, g) => n + g.rows.length, 0);
	const pages = isAll ? 1 : Math.max(1, Math.ceil(total / LIMIT));
	const current = Math.min(page, pages);
	const visibleGroups = isAll
		? groups.filter((g) => g.rows.length)
		: groups.map((g) => ({
				...g,
				rows: g.rows.slice((current - 1) * LIMIT, current * LIMIT),
			}));

	if (!wantsInstamart) return null;

	const firstColLabel = isAll ? "Asset" : TYPE_LABEL[dimension];
	const colCount = 9;

	const nameCell = (r) => {
		if (r._dim === "product") {
			return (
				<button
					type="button"
					onClick={() => setOpenRow(r)}
					className="flex w-full items-center gap-2.5 text-left"
				>
					{r.image_link && (
						<img
							src={r.image_link}
							alt=""
							loading="lazy"
							className="h-8 w-8 shrink-0 rounded object-cover"
						/>
					)}
					<div className="min-w-0 truncate font-medium text-content hover:underline">
						{r.product_name ?? r.product_variant_id}
					</div>
				</button>
			);
		}
		return (
			<button
				type="button"
				onClick={() => setOpenRow(r)}
				className="min-w-0 truncate text-left font-medium text-content hover:underline"
			>
				{r.keyword}
			</button>
		);
	};

	// Just the count here, same as Blinkit's Keyword insights "Campaigns"
	// column — the names and each one's spend are one click away in the
	// drawer, not spelled out in the table.
	const campaignCount = (r) => {
		const n = r.campaigns?.length ?? 0;
		return n ? (
			formatNumber(n)
		) : (
			<span className="text-content-subtle">—</span>
		);
	};

	return (
		<>
		<Card
			title="Ad asset performance · Instamart"
			actions={
				<div className="flex flex-wrap items-center gap-2">
				<details className="relative" ref={menuRef}>
					<summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-sm font-medium text-content marker:content-none focus:outline-none focus:ring-2 focus:ring-brand/30">
						{isAll
							? "All assets"
							: DIMENSIONS.find((x) => x.key === dimension)?.label}
						<span className="text-[10px] text-content-subtle" aria-hidden>
							▾
						</span>
					</summary>
					<div className="absolute right-0 z-20 mt-1 min-w-40 overflow-hidden rounded-md border border-border bg-card py-1 shadow-lg">
						{DIMENSIONS.map((d) => (
							<button
								key={d.key}
								type="button"
								onClick={() => {
									setDimension(d.key);
									if (menuRef.current) menuRef.current.open = false;
								}}
								className={`flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left text-sm hover:bg-muted ${
									d.key === dimension
										? "font-medium text-content"
										: "text-content-muted"
								}`}
							>
								{d.label}
								{d.key === dimension && (
									<span className="text-brand" aria-hidden>
										✓
									</span>
								)}
							</button>
						))}
					</div>
				</details>
				</div>
			}
		>
			{isLoading && <Loading label="Loading Instamart ad assets…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(total === 0 ? (
					<EmptyState message="No Instamart ad asset data for this selection." />
				) : (
					<div className={isFetching ? "opacity-60 transition-opacity" : ""}>
						{isAll && (
							<p className="mb-3 text-xs text-content-subtle">
								Products and keywords are two views of the same
								spend, ranked together — not added up.
							</p>
						)}
						<div className="overflow-auto">
							<table className="w-full border-collapse text-sm">
								<thead className="sticky top-0 z-10 bg-card">
									<tr className="border-b border-border">
										<th className="px-3 py-2 text-left font-medium text-content-subtle">
											{firstColLabel}
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Campaigns
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Impressions
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Clicks
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											CTR
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											ATC
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Spend
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											GMV
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											RoAS
										</th>
									</tr>
								</thead>
								<tbody>
									{visibleGroups.map((g) => (
										<Fragment key={g.key}>
											{isAll && (
												<tr className="bg-muted/40">
													<th
														colSpan={colCount}
														scope="colgroup"
														className="px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-content-muted"
													>
														{TYPE_LABEL[g.key]}
														<span className="ml-1.5 font-normal normal-case tracking-normal text-content-subtle">
															({g.rows.length})
														</span>
													</th>
												</tr>
											)}
											{g.rows.map((r) => (
												<tr
													key={`${r._dim}-${r.product_variant_id ?? r.keyword}`}
													className="border-b border-border/60 last:border-0 hover:bg-muted/50"
												>
													<td className="px-3 py-2">{nameCell(r)}</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{campaignCount(r)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{formatNumber(r.impressions)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{formatNumber(r.clicks)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content-muted">
														{formatPct(r.ctr)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{formatNumber(r.atc)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{formatCurrency(r.spend)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{formatCurrency(r.sales)}
													</td>
													<td className="px-3 py-2 text-right tabular-nums text-content">
														{formatRoas(r.roas)}
													</td>
												</tr>
											))}
										</Fragment>
									))}
								</tbody>
							</table>
						</div>
						{!isAll && (
							<Pagination
								page={current}
								pages={pages}
								total={total}
								limit={LIMIT}
								onChange={setPage}
							/>
						)}
					</div>
				))}
		</Card>
		<InstamartAssetDrawer
			row={openRow}
			range={range}
			open={openRow != null}
			onClose={() => setOpenRow(null)}
		/>
		</>
	);
};
