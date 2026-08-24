import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
	useZeptoBreakdown,
	useZeptoKeywords,
	useZeptoProducts,
} from "../hooks";
import { Card } from "../../../components/ui/Card";
import { Pagination } from "../../../components/ui/Pagination";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";
import { EmptyState } from "../../../components/feedback/EmptyState";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { formatCurrency, formatNumber } from "../../../lib/format";
import { AD_TYPE_OPTIONS, AdTypeSelect } from "./AdTypeSelect";

const LIMIT = 20;

const formatRoas = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}x`;
const formatPct = (v) =>
	v === null || v === undefined ? "—" : `${v.toFixed(2)}%`;

/** Breakdowns Zepto reports, plus the combined default.
 *
 * `product` and `keyword` have their own endpoints; `category` and `city` share
 * /ads/zepto-breakdown, which takes the dimension as a parameter.
 *
 * No "page" entry — the client does not want the placement breakdown on the
 * dashboard. It is still scraped (zepto_ad_breakdown_daily, dimension = 'page')
 * and the endpoint still serves it, so restoring it is one line here.
 */
const DIMENSIONS = [
	{ key: "all", label: "All" },
	{ key: "product", label: "Product" },
	{ key: "keyword", label: "Keyword" },
	{ key: "category", label: "Category" },
	{ key: "city", label: "City" },
];

const TYPE_LABEL = {
	product: "Product",
	keyword: "Keyword",
	category: "Category",
	city: "City",
};

const MATCH_OPTIONS = [
	{ value: "", label: "All match types" },
	{ value: "BROAD", label: "Broad" },
	{ value: "PHRASE", label: "Phrase" },
	{ value: "EXACT", label: "Exact" },
];

/** Every Zepto ad asset breakdown in one card, combined by default.
 *
 * Replaces the four separate Product / Keyword / Category / City cards. Zepto's
 * own Analytics page presents these as tabs inside one section rather than as
 * separate blocks, and four cards showing the same six metrics under different
 * groupings made the page long without making it clearer.
 *
 * ── An important caveat about the "All" view ──────────────────────────────
 * These four are not different assets; they are four ways of slicing the SAME
 * spend. Each one independently sums to the account total — Rs 46,314 for
 * 14-21 Aug whether grouped by product, keyword, category or city. So the
 * combined list is a UNION of four breakdowns, not an additive whole: summing
 * its Spend column would count the same money four times over.
 *
 * That is why the combined view is split into headed sections rather than one
 * interleaved list, why rows are ranked by spend rather than totalled, and why
 * no total is shown anywhere on this card. Blinkit's equivalent behaves
 * differently — there, keyword and recommendation rows are genuinely distinct
 * targets that do sum to the account total.
 *
 * Match type sits under the keyword rather than in a column. The ad-type tag
 * was dropped from these rows: it labels the ad product (Sponsored Products /
 * Brands / Display), which beside a keyword or a city reads as though the row
 * itself were a product. The ad-type dropdown covers that dimension already.
 */
export const ZeptoAssetPerformanceCard = () => {
	const [dimension, setDimension] = useState("all");
	const [adType, setAdType] = useState("");
	const [matchType, setMatchType] = useState("");
	const [page, setPage] = useState(1);
	const menuRef = useRef(null);

	const { selected } = useMarketplaces();
	const wantsZepto = !selected?.length || selected.includes("zepto");

	useEffect(() => {
		setPage(1);
	}, [dimension, adType, matchType, selected]);

	const isAll = dimension === "all";
	const isProduct = dimension === "product";
	const isKeyword = dimension === "keyword";

	// Hooks always run — React requires it — but each is enabled only when its
	// data is on screen, so a single-dimension view makes one request, not four.
	const products = useZeptoProducts({
		campaignCategory: adType,
		enabled: isAll || isProduct,
	});
	const keywords = useZeptoKeywords({ enabled: isAll || isKeyword });
	const categories = useZeptoBreakdown({
		dimension: "category",
		campaignCategory: adType,
		enabled: isAll || dimension === "category",
	});
	const cities = useZeptoBreakdown({
		dimension: "city",
		campaignCategory: adType,
		enabled: isAll || dimension === "city",
	});

	const sources = {
		product: products,
		keyword: keywords,
		category: categories,
		city: cities,
	};
	const shown = isAll ? Object.keys(sources) : [dimension];

	const isLoading = shown.some((k) => sources[k].isLoading);
	const error = shown.map((k) => sources[k].error).find(Boolean) ?? null;
	const isFetching = shown.some((k) => sources[k].isFetching);
	const refetch = () => shown.forEach((k) => sources[k].refetch());

	/** One entry per breakdown on screen, each with its own rows ranked by spend.
	 *
	 * Grouped rather than interleaved so the combined view reads as "products,
	 * then keywords, then categories, then cities" with a heading on each —
	 * which also makes it visually obvious that these are separate slicings of
	 * the same spend rather than one additive list.
	 */
	const groups = useMemo(() => {
		return shown.map((key) => {
			let data = sources[key].data ?? [];
			// The keyword endpoint takes no ad-type parameter, so that filter is
			// applied here; match type is client-side for the same reason.
			if (key === "keyword") {
				if (adType) data = data.filter((r) => r.ad_types?.includes(adType));
				if (matchType) data = data.filter((r) => r.match_type === matchType);
			}
			return {
				key,
				rows: [...data]
					.sort((a, b) => (b.spend ?? 0) - (a.spend ?? 0))
					.map((r) => ({ ...r, _dim: key })),
			};
		});
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [
		products.data,
		keywords.data,
		categories.data,
		cities.data,
		dimension,
		adType,
		matchType,
	]);

	const total = groups.reduce((n, g) => n + g.rows.length, 0);
	// Paginated only on a single breakdown; the grouped view shows each section
	// whole, since paging across headings splits them in half.
	const pages = isAll ? 1 : Math.max(1, Math.ceil(total / LIMIT));
	const current = Math.min(page, pages);
	const visibleGroups = isAll
		? groups.filter((g) => g.rows.length)
		: groups.map((g) => ({
				...g,
				rows: g.rows.slice((current - 1) * LIMIT, current * LIMIT),
			}));

	if (!wantsZepto) return null;

	const showMatchFilter = isAll || isKeyword;
	const firstColLabel = isAll ? "Asset" : TYPE_LABEL[dimension];
	// Name + Impressions, Clicks, CTR, Orders, ATC, Spend, Sales, RoAS.
	const colCount = 9;

	const nameCell = (r) => {
		if (r._dim === "product")
			return (
				<div className="flex items-center gap-2.5">
					{r.image_link && (
						<img
							src={r.image_link}
							alt=""
							loading="lazy"
							className="h-8 w-8 shrink-0 rounded object-cover"
						/>
					)}
					<div className="min-w-0">
						<div className="truncate font-medium text-content">
							{r.product_name ?? r.product_variant_id}
						</div>
						<div className="text-xs text-content-subtle">
							{r.product_category ?? "—"}
						</div>
					</div>
				</div>
			);
		return (
			<div className="min-w-0">
				<div className="truncate font-medium text-content">
					{r._dim === "keyword" ? r.keyword : r.name}
				</div>
				{/* No ad-type tag: it names the AD TYPE (Sponsored Products /
				    Brands / Display), which on a keyword row reads as though the
				    keyword were a product. The ad-type dropdown already controls
				    that dimension. Keywords use the space for match type, which
				    is otherwise invisible now the Match column is gone. */}
				{r._dim === "keyword" && r.match_type && (
					<div className="text-xs text-content-subtle">
						{r.match_type}
					</div>
				)}
			</div>
		);
	};

	return (
		<Card
			title="Ad asset performance · Zepto"
			actions={
				<div className="flex flex-wrap items-center gap-2">
					<AdTypeSelect
						value={adType}
						onChange={setAdType}
						options={AD_TYPE_OPTIONS}
					/>
					{/* A menu rather than a <select>, so the control keeps reading
					    "Campaign performance" instead of swapping to the chosen
					    option. <details> gives click-to-open with no open/close
					    state to manage; a pick closes it via `open = false`. */}
					<details className="relative" ref={menuRef}>
						<summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-sm font-medium text-content marker:content-none focus:outline-none focus:ring-2 focus:ring-brand/30">
							Campaign performance
							<span
								className="text-[10px] text-content-subtle"
								aria-hidden
							>
								▾
							</span>
						</summary>
						<div className="absolute right-0 z-20 mt-1 min-w-44 overflow-hidden rounded-md border border-border bg-card py-1 shadow-lg">
							{DIMENSIONS.map((d) => (
								<button
									key={d.key}
									type="button"
									onClick={() => {
										setDimension(d.key);
										if (menuRef.current)
											menuRef.current.open = false;
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
					{showMatchFilter && (
						<select
							value={matchType}
							onChange={(e) => setMatchType(e.target.value)}
							className="rounded-md border border-border bg-card px-2.5 py-1 text-sm text-content focus:outline-none focus:ring-2 focus:ring-brand/30"
						>
							{MATCH_OPTIONS.map((o) => (
								<option key={o.value} value={o.value}>
									{o.label}
								</option>
							))}
						</select>
					)}
				</div>
			}
		>
			{isLoading && <Loading label="Loading Zepto ad assets…" />}
			{error && <ErrorState message={error.message} onRetry={refetch} />}
			{!isLoading &&
				!error &&
				(total === 0 ? (
					<EmptyState message="No Zepto ad asset data for this selection." />
				) : (
					<div
						className={
							isFetching ? "opacity-60 transition-opacity" : ""
						}
					>
						{isAll && (
							<p className="mb-3 text-xs text-content-subtle">
								Products, keywords, categories and cities are four
								views of the same spend, ranked together — not
								added up.
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
											Impressions
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Clicks
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											CTR
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Orders
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											ATC
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Spend
										</th>
										<th className="px-3 py-2 text-right font-medium text-content-subtle">
											Sales
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
											key={`${r._dim}-${r.product_variant_id ?? r.keyword ?? r.name}-${r.match_type ?? ""}`}
											className="border-b border-border/60 last:border-0 hover:bg-muted/50"
										>
											<td className="px-3 py-2">{nameCell(r)}</td>
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
												{formatNumber(r.units_sold)}
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
						{/* No pager on the grouped view — every section is shown
						    whole there, so a "1–20 of 95" footer would be wrong. */}
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
	);
};
