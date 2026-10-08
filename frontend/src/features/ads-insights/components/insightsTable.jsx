import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronRight, ChevronsUpDown } from "lucide-react";
import { HoverHint } from "../../../components/ui/HoverHint";
import { MarketplaceMark } from "../../../components/ui/MarketplaceMark";
import { useMarketplaces } from "../../../context/MarketplaceContext";
import { marketplaceName } from "../../../lib/marketplace";
import { sortRows } from "../../../lib/sortRows";

/**
 * Which marketplace a row belongs to: its mark, plus the name unless `compact`. Rows from
 * several marketplaces sit in one table on this page, so a row has to say whose it is.
 */
export const MarketplaceTag = ({ slug, compact = false }) => {
	const { marketplaces } = useMarketplaces();
	const mp = marketplaces.find((m) => m.slug === slug) ?? {
		slug,
		name: marketplaceName(slug),
	};
	return (
		<span
			className="inline-flex items-center gap-1.5"
			title={compact ? marketplaceName(slug) : undefined}
		>
			<MarketplaceMark marketplace={mp} size={16} />
			{!compact && (
				<span className="text-content-muted">
					{marketplaceName(slug)}
				</span>
			)}
		</span>
	);
};

/**
 * The shared parts of an insights table.
 *
 * Campaign, keyword and category insights are the same object three times over: a wide
 * table of numbers, a header that explains itself on hover, sorting on every column, and a
 * download. Keeping the pieces here is what stops the three from drifting into three
 * different-looking tables.
 */
/** "EXACT_MATCH" reads as "Exact Match". Platform enums are shouted; the table is not.
 * A short all-caps word is an acronym, not a shout, and stays as it is: Zepto's "PLA" read
 * "Pla". Already-cased words ("Display") pass through the same split unharmed. */
export const enumLabel = (raw) => {
	if (!raw) return "—";
	const s = String(raw);
	if (/^[A-Z]{2,3}$/.test(s)) return s;
	return s
		.toLowerCase()
		.split("_")
		.map((w) => w.charAt(0).toUpperCase() + w.slice(1))
		.join(" ");
};

export const TH =
	"whitespace-nowrap px-3 py-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-content-subtle";
// py-3 rather than py-2: these tables are wide, and a row needs enough height to be
// followed across fourteen columns without the eye slipping to its neighbour.
export const TD = "whitespace-nowrap px-3 py-3 text-sm text-content";
export const NUM = `${TD} text-right tabular-nums`;

/**
 * Sticky identity column on the left; the metrics scroll under it. Sticky cells paint
 * their own background, because the scrolling columns slide visibly underneath otherwise.
 */
export const STICKY_NAME =
	"sticky left-0 z-20 overflow-hidden border-r border-border bg-card";

/**
 * The header row, frozen to the top of its own scroll box.
 *
 * ⚠️ A background on a sticky `<thead>` is not painted, so it goes on every `<th>` instead;
 * without it the rows scroll visibly THROUGH the header. The identity header needs a higher
 * stack order still, because it is frozen in both directions at once and has to cover the
 * scrolling headers as well as the scrolling rows.
 */
export const STICKY_HEAD = "sticky top-0 z-10 bg-card";

/** The hover fill for a frozen cell and for the row it belongs to. Opaque, deliberately. */
export const ROW_HOVER = "hover:bg-muted";
export const STICKY_HOVER = "group-hover:bg-muted";
export const LIFTED_L = "shadow-[6px_0_10px_-6px_rgba(0,0,0,0.35)]";

/**
 * Click-to-sort over rows already in hand. Keys are STRINGS deliberately: an inline
 * accessor function is a new identity on every render, so comparing keys by function never
 * matched and clicking a column could never toggle its direction.
 *
 * Client-side on purpose: these endpoints sort on a handful of keys, and a derived column
 * (ACoS, AOV, share) has no server key at all. Sorting the loaded rows is honest as long as
 * the caller says what is loaded, which is why the cards state their row count.
 */
export const useClientSort = (
	rows,
	accessors,
	initialKey,
	initialOrder = "desc",
) => {
	const [sort, setSort] = useState(initialKey);
	const [order, setOrder] = useState(initialOrder);

	const sorted = useMemo(() => {
		return sortRows(rows, accessors[sort], order);
		// `accessors` is rebuilt each render by design (it closes over the row shape), so it
		// is deliberately not a dependency; the key string is what decides the order.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [rows, sort, order]);

	const onSort = (key) => {
		if (key === sort) setOrder((o) => (o === "desc" ? "asc" : "desc"));
		else {
			setSort(key);
			setOrder("desc");
		}
	};

	return { sorted, sort, order, onSort };
};

/**
 * A sortable, self-explaining column heading. The whole cell is the hover target.
 *
 * Labels are CENTRED over their column while the values below keep their own alignment
 * (numbers right, names left). The header then reads as a band of labels rather than
 * inheriting the ragged edges of the data underneath it.
 */
export const SortHead = ({
	label,
	hint,
	sortKey,
	sort,
	order,
	onSort,
	className = "",
}) => {
	const active = sortKey && sort === sortKey;
	const Arrow = active
		? order === "asc"
			? ArrowUp
			: ArrowDown
		: ChevronsUpDown;
	const inner = (
		<span
			className={`inline-flex items-center gap-1 ${
				hint
					? "decoration-content-subtle/40 decoration-dotted underline-offset-4 hover:decoration-content-subtle hover:underline"
					: ""
			}`}
		>
			{label}
			{sortKey && (
				<Arrow
					size={11}
					className={active ? "text-brand" : "text-content-subtle/50"}
					aria-hidden
				/>
			)}
		</span>
	);
	return (
		<th
			aria-sort={
				active
					? order === "asc"
						? "ascending"
						: "descending"
					: undefined
			}
			className={`${TH} ${STICKY_HEAD} text-center ${className}`}
		>
			<HoverHint
				label={hint}
				tabIndex={sortKey ? undefined : 0}
				className="w-full justify-center"
			>
				{sortKey ? (
					<button
						type="button"
						onClick={() => onSort(sortKey)}
						className={`uppercase tracking-[0.08em] transition-colors hover:text-content ${active ? "text-content" : ""}`}
					>
						{inner}
					</button>
				) : (
					inner
				)}
			</HoverHint>
		</th>
	);
};

/**
 * The identity cell every insights table starts with.
 *
 * Frozen to the left so a number is never separated from the row it belongs to, truncated
 * so the metrics keep the screen, and opening that row's detail on click. The full text is
 * on hover because truncation is what hides it, and through HoverHint rather than a native
 * `title`, which the browser draws in its own font after its own delay.
 */
export const NameCell = ({
	name,
	hint,
	onOpen,
	scrolled,
	width = "15rem",
	children,
}) => (
	// ⚠️ The width lives on the CONTENT, not the cell. `table-layout: auto` sizes a column to
	// what is inside it and ignores max-width on a `th`/`td`, so constraining the cell does
	// nothing and the longest name decides the column. A fixed-width block inside it is what
	// the algorithm actually measures.
	<td
		className={`${TD} ${STICKY_NAME} ${scrolled ? LIFTED_L : ""} ${STICKY_HOVER}`}
	>
		<div style={{ width }}>
			<HoverHint label={hint} className="w-full">
				{/* The row opens a detail view, and the reader has to be able to tell that without
			    being told. The pointer, the underline and an arrow that slides in on hover all
			    live ON the cell; a tooltip cannot carry the message, because it is
			    `pointer-events-none` and vanishes the moment you move toward it. The tooltip is
			    left to say what the cell cannot fit. */}
				<button
					type="button"
					onClick={onOpen}
					className="group/name flex w-full max-w-full cursor-pointer items-center gap-1 text-left font-medium text-content transition-colors hover:text-brand"
				>
					<span className="truncate group-hover/name:underline">
						{children ?? name}
					</span>
					<ChevronRight
						size={13}
						aria-hidden
						className="shrink-0 -translate-x-1 opacity-0 transition-all group-hover/name:translate-x-0 group-hover/name:opacity-100"
					/>
				</button>
			</HoverHint>
		</div>
	</td>
);

/**
 * A small table inside a drawer section, WITH headers — every drawer list uses this, so a
 * column of numbers always says what it is. `head` is `[{ label, align }]`; `rows` is
 * `[{ key, cells }]`, one cell per head entry. Right-aligned columns are numbers.
 */
export const MiniTable = ({ head, rows }) => (
	<table className="w-full border-collapse text-sm">
		<thead>
			<tr className="border-b border-border text-[11px] tracking-[0.08em] text-content-subtle uppercase">
				{head.map((h) => (
					<th
						key={h.label}
						className={`px-2 py-2 font-semibold first:pl-0 last:pr-0 ${h.align === "right" ? "text-right" : "text-left"}`}
					>
						{h.label}
					</th>
				))}
			</tr>
		</thead>
		<tbody>
			{rows.map((r) => (
				<tr
					key={r.key}
					className="border-b border-border/60 last:border-0"
				>
					{r.cells.map((c, i) => (
						<td
							key={head[i].label}
							className={`px-2 py-1.5 first:pl-0 last:pr-0 ${head[i].align === "right" ? "text-right tabular-nums" : "max-w-56"}`}
						>
							{c}
						</td>
					))}
				</tr>
			))}
		</tbody>
	</table>
);

/**
 * A section's download, placed above the card rather than inside its header.
 *
 * The controls in the header narrow what the section shows; this one takes what the section
 * shows away with you. Sitting them together made the download read as a fourth filter.
 */
export const SectionExport = ({ children }) => (
	<div className="mb-1.5 flex justify-end">{children}</div>
);
