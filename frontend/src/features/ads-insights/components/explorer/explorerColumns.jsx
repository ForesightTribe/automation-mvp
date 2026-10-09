import { CampaignStatusBadge } from "../../../../components/ui/CampaignStatusBadge";
import { formatCurrency, formatNumber } from "../../../../lib/format";
import { marketplaceName } from "../../../../lib/marketplace";
import { BuDots } from "../BuDots";

/**
 * The explorer's columns. Which ones a table shows is the viewer's choice (the Columns
 * picker); the order is fixed here.
 *
 * Every column has a plain definition on hover (the header's hint), a `value` for sorting and
 * the CSV, and a `render` for the cell. A null figure renders "—" with a hover naming the
 * marketplace that does not report it.
 */

/** What each column measures, in plain terms. */
const ABOUT = {
	spend: "The money spent on ads.",
	sales: "Sales the marketplace attributes to the ads. On Blinkit keywords: direct plus indirect.",
	roas: "Return on ad spend: sales divided by spend. Red below 1× (losing money), amber 1–3×, green 3× and above.",
	acos: "Advertising cost of sale: spend as a percentage of sales. Lower is better.",
	impressions: "How many times the ads were shown.",
	clicks: "How many times the ads were clicked. Zepto and Instamart report it; Blinkit does not.",
	ctr: "Click-through rate: clicks as a percentage of impressions.",
	atc: "Adds to cart the marketplace attributes to the ads.",
	orders: "Units sold on Blinkit; orders on Zepto, which counts orders rather than units. Instamart reports neither reliably.",
	conv: "Conversion: orders as a percentage of clicks.",
	cpm: "Cost per thousand impressions.",
	cpc: "Cost per click: spend divided by clicks.",
	cpo: "Cost per order: spend divided by orders.",
	position:
		"Where the ad most often appeared in the results; lower is nearer the top. Blinkit reports it per keyword.",
	sov: "Share of voice. Blinkit reports it per keyword, Zepto per campaign (a trailing 7-day figure).",
	status: "Whether the campaign is running, paused, on hold or finished, in its marketplace's own word.",
	budget: "The campaign's current daily budget.",
	bu: "Budget utilisation for each of the last 7 days, oldest on the left. Green is 85% and over, amber 60 to 85%, red under 60%, grey means it did not run. Hover a dot for the figures, click it for the full trend. Sorting uses the same 7 days, counting only days it ran.",
};

const na = (row, what = "this") => (
	<span
		className="cursor-help text-content-subtle"
		title={`${(row.platforms ?? []).map(marketplaceName).join(" / ") || "This marketplace"} doesn't report ${what}`}
	>
		—
	</span>
);
const num = (row, v, what) =>
	v == null ? na(row, what) : formatNumber(Math.round(v));
const money = (row, v, what) => (v == null ? na(row, what) : formatCurrency(v));
const pct = (row, v, what, d = 1) =>
	v == null ? na(row, what) : `${v.toFixed(d)}%`;

/** RoAS against 1× (losing money) and the 3× target. The number is always printed, so the
 * colour speeds the scan and is never the only signal. */
export const RoasPill = ({ value }) =>
	value == null ? (
		<span className="text-content-subtle">—</span>
	) : (
		// Coloured text, no fill — the same treatment as the app's delta badges.
		<span
			className={`font-semibold tabular-nums ${
				value < 1
					? "text-danger"
					: value < 3
						? "text-warning"
						: "text-success"
			}`}
		>
			{value.toFixed(2)}x
		</span>
	);

/** Budget used over the 7 days the dots show, on the days it ran — a ratio of sums. */
export const bu7 = (row) => {
	const ran = (row.bu ?? []).filter((d) => d.bu != null);
	const allowed = ran.reduce((s, d) => s + d.allowed, 0);
	return allowed
		? (ran.reduce((s, d) => s + d.spend, 0) / allowed) * 100
		: null;
};

const C = {
	spend: {
		label: "Spend",

		value: (r) => r.spend,
		render: (r) => formatCurrency(r.spend),
	},
	sales: {
		label: "Sales",

		value: (r) => r.sales,
		render: (r) => formatCurrency(r.sales),
	},
	roas: {
		label: "RoAS",

		value: (r) => r.roas,
		render: (r) => <RoasPill value={r.roas} />,
	},
	acos: {
		label: "ACoS",

		value: (r) => r.acos,
		render: (r) => pct(r, r.acos, "sales"),
	},
	impressions: {
		label: "Impr.",

		value: (r) => r.impressions,
		render: (r) => formatNumber(r.impressions),
	},
	clicks: {
		label: "Clicks",

		value: (r) => r.clicks,
		render: (r) => num(r, r.clicks, "clicks"),
	},
	ctr: {
		label: "CTR",

		value: (r) => r.ctr,
		render: (r) => pct(r, r.ctr, "clicks", 2),
	},
	atc: {
		label: "Add to cart",

		value: (r) => r.atc,
		render: (r) => num(r, r.atc, "add-to-carts"),
	},
	orders: {
		label: "Orders",

		value: (r) => r.orders,
		render: (r) => num(r, r.orders, "orders"),
	},
	conv: {
		label: "Conv.",

		value: (r) => r.conv,
		render: (r) => pct(r, r.conv, "clicks and orders together"),
	},
	cpm: {
		label: "CPM",

		value: (r) => r.cpm,
		render: (r) => money(r, r.cpm, "impressions"),
	},
	cpc: {
		label: "CPC",

		value: (r) => r.cpc,
		render: (r) => money(r, r.cpc, "clicks"),
	},
	cpo: {
		label: "Cost / order",

		value: (r) => r.cpo,
		render: (r) => money(r, r.cpo, "orders"),
	},
	position: {
		label: "Position",

		value: (r) => r.position,
		render: (r) =>
			r.position == null ? na(r, "ad position") : `#${r.position}`,
	},
	sov: {
		label: "SOV",

		value: (r) => r.sov,
		render: (r) =>
			pct(
				r,
				r.sov,
				"share of voice here",
				r.sov != null && r.sov < 1 ? 2 : 1,
			),
	},
	status: {
		label: "Status",

		value: (r) => r.state ?? r.status ?? "",
		render: (r) => <CampaignStatusBadge status={r.status} />,
		align: "left",
	},
	budget: {
		label: "Budget",

		value: (r) => r.daily_budget,
		render: (r) =>
			r.daily_budget != null
				? formatCurrency(r.daily_budget)
				: na(r, "a daily budget"),
	},
	bu: {
		label: "BU 7d",

		value: bu7,
		render: (r, ctx) =>
			r.bu ? (
				<BuDots
					days={r.bu}
					campaignName={r.name}
					onShow={ctx.buTip.show}
					onHide={ctx.buTip.hide}
					onClick={(e) => {
						e?.stopPropagation?.();
						ctx.onBu(r.campaign);
					}}
				/>
			) : (
				<span className="text-content-subtle">—</span>
			),
		csv: (r) => (bu7(r) == null ? "" : bu7(r).toFixed(1)),
	},
};

/** Every column, in the order the table shows them. The picker never reorders. */
const ORDER = [
	"status",
	"budget",
	"bu",
	"spend",
	"sales",
	"roas",
	"acos",
	"impressions",
	"clicks",
	"ctr",
	"cpc",
	"cpm",
	"atc",
	"orders",
	"conv",
	"cpo",
	"position",
	"sov",
];
/** Columns that only mean something for some groupings. */
const ONLY = {
	status: ["campaign"],
	budget: ["campaign"],
	bu: ["campaign"],
	position: ["keyword"],
	sov: ["campaign", "keyword"],
};
/** What a table shows before anyone changes it — the six figures most questions start with,
 * plus a campaign's settings and pacing. */
export const DEFAULT_COLUMNS = [
	"status",
	"budget",
	"bu",
	"spend",
	"sales",
	"roas",
	"impressions",
	"clicks",
	"cpm",
];

/** The columns a grouping can show, in table order. */
export const availableColumns = (dim) =>
	ORDER.filter((k) => !ONLY[k] || ONLY[k].includes(dim)).map((k) => ({
		key: k,
		hint: ABOUT[k],
		// The picker uses the column's own header, so the two never read differently.
		name: C[k].label,
		...C[k],
	}));

/** The columns shown for a grouping: the picked ones it can show, in table order. */
export const columnsFor = (dim, shown) =>
	availableColumns(dim).filter((c) => shown.includes(c.key));

/** Figures a totals row can honestly carry (additive, or rebuilt from additive bases). */
export const TOTAL_KEYS = new Set([
	"spend",
	"sales",
	"roas",
	"acos",
	"impressions",
	"clicks",
	"ctr",
	"atc",
	"orders",
	"conv",
	"cpm",
	"cpc",
	"cpo",
]);
