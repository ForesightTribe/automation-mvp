/**
 * The Performance explorer's data model: one row shape for campaigns, keywords, products,
 * categories and cities, from every marketplace that reports them.
 *
 * A row is built from LEAVES — one per marketplace figure set (a campaign, a campaign ×
 * keyword, a product…) — summed into additive bases. Ratios are rebuilt from those bases,
 * never averaged, and ONLY from the leaves that report both halves: Blinkit reports no clicks,
 * so a keyword combined across Blinkit and Zepto takes its CTR from Zepto's clicks over
 * Zepto's impressions, not over everyone's. A figure no leaf reports stays null ("—"), never 0.
 */
import { marketplaceName } from "../../../../lib/marketplace";
import { enumLabel } from "../insightsTable";

// The API also serves category and city; both are breakdowns of the same spend
// these three already account for.
export const DIMS = [
	{ value: "campaign", label: "Campaign" },
	{ value: "keyword", label: "Keyword" },
	{ value: "product", label: "Product" },
];
export const DIM_LABEL = Object.fromEntries(
	DIMS.map((d) => [d.value, d.label]),
);
export const NOUN = {
	campaign: "campaigns",
	keyword: "keywords",
	product: "products",
	category: "categories",
	city: "cities",
};

/**
 * Which marketplaces report each grouping. Mirrors the backend: campaigns from
 * `ads_service.get_campaigns`, keywords from `get_keyword_insights`, the rest from
 * `BREAKDOWN_MARKETPLACES` (Blinkit reports no product / category / city ad data —
 * BLINKIT-NOTES B7). A marketplace in view but not listed shows as "not reported".
 */
export const COVER = {
	campaign: ["blinkit", "zepto", "instamart"],
	keyword: ["blinkit", "zepto", "instamart"],
	product: ["zepto", "instamart"],
	category: ["zepto"],
	city: ["zepto"],
};

/** Sum of a field over leaves, or null when no leaf reports it. */
const sumOf = (leaves, pick) => {
	let n = null;
	for (const l of leaves) {
		const v = pick(l);
		if (v != null) n = (n ?? 0) + v;
	}
	return n;
};

/** Additive bases + the derived ratios for a set of leaves. */
export const figures = (leaves) => {
	const spend = sumOf(leaves, (l) => l.spend) ?? 0;
	const sales = sumOf(leaves, (l) => l.sales) ?? 0;
	const impressions = sumOf(leaves, (l) => l.impressions) ?? 0;
	const clicks = sumOf(leaves, (l) => l.clicks);
	const orders = sumOf(leaves, (l) => l.orders);
	const atc = sumOf(leaves, (l) => l.atc);
	const withClicks = leaves.filter((l) => l.clicks != null);
	const withOrders = leaves.filter((l) => l.orders != null);
	const withBoth = withClicks.filter((l) => l.orders != null);
	const impC = sumOf(withClicks, (l) => l.impressions) ?? 0;
	const spendC = sumOf(withClicks, (l) => l.spend) ?? 0;
	const spendO = sumOf(withOrders, (l) => l.spend) ?? 0;
	const clicksB = sumOf(withBoth, (l) => l.clicks) ?? 0;
	const ordersB = sumOf(withBoth, (l) => l.orders) ?? 0;
	// Blinkit's keyword CPM is its own reported figure, not spend ÷ impressions (351 against
	// 358): those leaves contribute their reported rate, the rest their derived one.
	const cpmNum = leaves.reduce(
		(s, l) =>
			s +
			(l.cpm != null
				? l.cpm * (l.impressions ?? 0)
				: (l.spend ?? 0) * 1000),
		0,
	);
	return {
		spend,
		sales,
		impressions,
		clicks,
		orders,
		atc,
		roas: spend ? sales / spend : null,
		acos: sales ? (spend / sales) * 100 : null,
		ctr: clicks != null && impC ? (clicks / impC) * 100 : null,
		cpc: clicks ? spendC / clicks : null,
		cpm: impressions ? cpmNum / impressions : null,
		cpo: orders ? spendO / orders : null,
		conv: clicksB ? (ordersB / clicksB) * 100 : null,
	};
};

const norm = (s) =>
	String(s ?? "")
		.trim()
		.toLowerCase();

/** Rows grouped by `keyOf`, each with its marketplaces, leaves and — when they span more
 * than one marketplace — a child row per marketplace. `extra(members)` adds the grouping's
 * own fields. */
const group = (items, keyOf, toLeaf, extra, childKey) => {
	const by = new Map();
	for (const it of items) {
		const k = keyOf(it);
		if (!by.has(k)) by.set(k, []);
		by.get(k).push(it);
	}
	return [...by.entries()].map(([key, members]) => {
		const platforms = [...new Set(members.map((m) => m.platform))];
		const row = {
			key,
			platforms,
			members,
			...figures(members.map(toLeaf)),
			...extra(members),
		};
		if (platforms.length > 1 && childKey)
			row.kids = group(members, childKey, toLeaf, extra).sort(
				(a, b) => b.spend - a.spend,
			);
		return row;
	});
};

/** Campaigns: never combined — a campaign belongs to one marketplace. */
export const campaignRows = (items, { buByKey, zeptoSov }) =>
	items.map((c) => {
		const key = `${c.platform}:${c.campaign_id}`;
		return {
			key,
			name: c.name ?? String(c.campaign_id),
			sub: `${marketplaceName(c.platform)} · ${enumLabel(c.type)}`,
			platforms: [c.platform],
			campaign: c,
			status: c.status,
			state: c.state,
			type: c.type,
			daily_budget: c.daily_budget,
			bu: buByKey.get(key) ?? null,
			sov:
				c.platform === "zepto"
					? (zeptoSov.get(c.campaign_id) ?? null)
					: null,
			...figures([
				{
					spend: c.budget_consumed,
					sales: c.ad_sales,
					impressions: c.impressions,
					clicks: c.clicks ?? null,
					atc: c.atc,
					// Instamart's units figure is unreliable (confirmed 2026-09-30) — withheld.
					orders:
						c.platform === "instamart" ? null : c.quantities_sold,
				},
			]),
		};
	});

const keywordLeaf = (r) => ({
	spend: r.spend,
	sales: r.sales,
	impressions: r.impressions,
	clicks: r.clicks ?? null,
	atc: r.atc ?? null,
	orders: r.orders ?? null,
	cpm: r.cpm ?? null,
});

/** Keywords: one row per search term per marketplace, or per term across marketplaces when
 * combined (each marketplace then a child row). `blinkitSov` maps a keyword to its SOV. */
export const keywordRows = (items, { combine, blinkitSov }) =>
	group(
		items,
		(r) => (combine ? norm(r.keyword) : `${r.platform}:${norm(r.keyword)}`),
		keywordLeaf,
		(members) => {
			const positions = members
				.map((m) => m.position)
				.filter((p) => p != null);
			const onBlinkit = members.some((m) => m.platform === "blinkit");
			return {
				name: members[0].keyword,
				match_types: [
					...new Set(
						members.map((m) => m.match_type).filter(Boolean),
					),
				],
				campaigns: new Set(
					members.map((m) => `${m.platform}:${m.campaign_id}`),
				).size,
				position: positions.length ? Math.min(...positions) : null,
				sov: onBlinkit
					? (blinkitSov.get(norm(members[0].keyword)) ?? null)
					: null,
			};
		},
		combine ? (r) => `${r.platform}:${norm(r.keyword)}` : null,
	);

const breakdownLeaf = (r) => ({
	spend: r.spend,
	sales: r.sales,
	impressions: r.impressions,
	clicks: r.clicks ?? null,
	atc: r.atc ?? null,
	orders: r.units_sold ?? null,
});

/** Products, categories, cities: combined by name across marketplaces when asked. */
export const breakdownRows = (items, { combine }) =>
	group(
		items,
		(r) => (combine ? norm(r.name) : `${r.platform}:${r.key}`),
		breakdownLeaf,
		(members) => ({
			name: members[0].name,
			sub: members[0].detail ?? null,
			image: members.find((m) => m.image_link)?.image_link ?? null,
		}),
		combine ? (r) => `${r.platform}:${r.key}` : null,
	);
