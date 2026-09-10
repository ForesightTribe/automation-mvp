import { useState } from "react";

/**
 * The pieces every row on this page is built from — budget schedules, bid rules and
 * campaigns alike. They share one skeleton (badge + identity, a strip of labelled facts,
 * actions) so the three bands line up column-for-column and read as one system rather
 * than three lists that happen to sit on the same page.
 */

/** One labelled fact in a row. The label rides with the value rather than sitting in a
 *  table header, because the rows reflow into a stacked card on narrow screens and a
 *  detached header would leave the numbers unexplained there. */
export const Fact = ({ label, value, hint, className = "" }) => (
	<span className={`block min-w-0 ${className}`}>
		<span className="block text-[10px] font-medium tracking-wide text-content-subtle uppercase">
			{label}
		</span>
		<span className="mt-0.5 block text-sm font-semibold text-content">
			{value}
		</span>
		{hint && (
			<span className="mt-0.5 block text-[11px] leading-tight text-content-muted">
				{hint}
			</span>
		)}
	</span>
);

/** Badge + the two identity lines, at a fixed badge width so every row's name starts at
 *  the same x. Names WRAP rather than truncate — knowing which campaign a row is about is
 *  the whole point of the list. `badge` is a node, not a status string, because the
 *  scheduled rows and the campaign rows speak different status vocabularies. */
export const Identity = ({ badge, title, subtitle, className = "" }) => (
	<span className={`flex min-w-0 items-start gap-2.5 ${className}`}>
		<span className="w-22 shrink-0 pt-0.5">{badge}</span>
		<span className="min-w-0">
			<span className="block text-sm leading-snug font-semibold wrap-break-word text-content">
				{title}
			</span>
			<span className="mt-0.5 block text-xs leading-snug wrap-break-word text-content-muted">
				{subtitle}
			</span>
		</span>
	</span>
);

export const Chevron = ({ open, onClick, label }) => (
	<button
		type="button"
		onClick={onClick}
		aria-expanded={open}
		aria-label={label}
		className="shrink-0 rounded-md p-1.5 text-content-subtle transition-colors hover:bg-muted hover:text-content"
	>
		<span
			className={`block text-base leading-none transition-transform ${open ? "rotate-90" : ""}`}
		>
			›
		</span>
	</button>
);

/** Text action for the expanded panel's footer, where buttons would be too loud. */
export const Action = ({ onClick, disabled, tone = "muted", children }) => {
	const tones = {
		muted: "text-content-muted hover:text-content",
		primary: "text-primary hover:text-primary-hover",
		danger: "text-content-subtle hover:text-danger",
	};
	return (
		<button
			type="button"
			onClick={onClick}
			disabled={disabled}
			className={`text-xs font-medium transition-colors disabled:opacity-40 ${tones[tone]}`}
		>
			{children}
		</button>
	);
};

/** Delete, armed in two steps — these rows delete automations, not drafts. */
export const ConfirmDelete = ({ onConfirm, children = "Delete" }) => {
	const [armed, setArmed] = useState(false);
	if (!armed)
		return (
			<Action tone="danger" onClick={() => setArmed(true)}>
				{children}
			</Action>
		);
	return (
		<span className="inline-flex items-center gap-2">
			<button
				type="button"
				onClick={onConfirm}
				className="text-xs font-semibold text-danger hover:underline"
			>
				Confirm delete
			</button>
			<Action onClick={() => setArmed(false)}>cancel</Action>
		</span>
	);
};

/** The shell of a row: a card whose header is a 12-column grid on wide screens and a
 *  stacked block below it. `facts` is wrapped in `lg:contents` by the caller so its
 *  children become columns of this grid at `lg`.
 *
 *  `onToggle` is optional. Rows that expand make the header itself the toggle; a campaign
 *  row has nothing to expand into on click, so it renders the same grid as a plain block
 *  rather than a button you can press to no effect. */
const HEADER =
	"grid w-full gap-3 text-left lg:col-span-9 lg:grid-cols-9 lg:items-center lg:gap-4";

export const RowShell = ({ onToggle, header, actions, children }) => (
	<li className="rounded-xl border border-border bg-surface">
		<div className="grid gap-3 p-3.5 lg:grid-cols-12 lg:items-center lg:gap-4">
			{onToggle ? (
				<button type="button" onClick={onToggle} className={HEADER}>
					{header}
				</button>
			) : (
				<div className={HEADER}>{header}</div>
			)}
			<div className="flex flex-wrap items-center gap-2 lg:col-span-3 lg:justify-end">
				{actions}
			</div>
		</div>
		{children && (
			<div className="border-t border-border/70 px-3.5 py-3.5 lg:px-4 lg:py-4">
				{children}
			</div>
		)}
	</li>
);
