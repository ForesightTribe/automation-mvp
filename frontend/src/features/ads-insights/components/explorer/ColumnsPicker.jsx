import { useEffect, useRef, useState } from "react";
import { Check, Columns3 } from "lucide-react";

/**
 * The explorer's column picker: a "Columns" button that opens a two-column checklist of every
 * column the current grouping can show, with "Reset to default" and "Show all".
 *
 * Ticking a box updates the table at once; the order of columns never changes here (it is
 * fixed in explorerColumns). At least one figure column always stays on, so a table can never
 * be emptied to just its names. Closes on a click outside or Escape.
 */
export const ColumnsPicker = ({ columns, shown, onChange, onReset }) => {
	const [open, setOpen] = useState(false);
	const ref = useRef(null);

	useEffect(() => {
		if (!open) return undefined;
		const onDown = (e) => {
			if (ref.current && !ref.current.contains(e.target)) setOpen(false);
		};
		const onKey = (e) => e.key === "Escape" && setOpen(false);
		document.addEventListener("mousedown", onDown);
		document.addEventListener("keydown", onKey);
		return () => {
			document.removeEventListener("mousedown", onDown);
			document.removeEventListener("keydown", onKey);
		};
	}, [open]);

	const on = columns.filter((c) => shown.includes(c.key));
	const toggle = (key) => {
		const next = shown.includes(key)
			? shown.filter((k) => k !== key)
			: [...shown, key];
		// Never empty the table to just its names.
		if (!columns.some((c) => next.includes(c.key))) return;
		onChange(next);
	};

	return (
		<div className="relative" ref={ref}>
			<button
				type="button"
				aria-haspopup="true"
				aria-expanded={open}
				onClick={() => setOpen((v) => !v)}
				className={`inline-flex items-center gap-1.5 rounded-lg border bg-card px-2.5 py-1 text-xs font-medium transition-colors ${
					open
						? "border-brand text-content"
						: "border-border text-content-muted hover:border-content-subtle hover:text-content"
				}`}
			>
				<Columns3 size={13} aria-hidden />
				Columns
				<span className="rounded-full bg-muted px-1.5 text-[11px] text-content-muted tabular-nums">
					{on.length}
				</span>
			</button>
			{open && (
				<div
					role="dialog"
					aria-label="Choose columns"
					className="absolute right-0 z-40 mt-1.5 w-80 rounded-xl border border-border bg-card p-3 shadow-xl"
				>
					<div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
						{columns.map((c) => {
							const checked = shown.includes(c.key);
							const last = checked && on.length === 1;
							return (
								<label
									key={c.key}
									title={
										last
											? "At least one column stays on"
											: c.hint
									}
									className={`flex items-center gap-2 rounded-md px-1.5 py-1 text-sm ${
										last
											? "cursor-not-allowed text-content-subtle"
											: "cursor-pointer text-content hover:bg-muted"
									}`}
								>
									<input
										type="checkbox"
										className="sr-only"
										checked={checked}
										disabled={last}
										onChange={() => toggle(c.key)}
									/>
									<span
										aria-hidden
										className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
											checked
												? "border-brand bg-brand text-on-brand"
												: "border-border bg-card"
										}`}
									>
										{checked && (
											<Check size={11} strokeWidth={3} />
										)}
									</span>
									<span className="truncate">{c.name}</span>
								</label>
							);
						})}
					</div>
					<div className="mt-2 flex items-center justify-between border-t border-border pt-2 text-xs">
						<button
							type="button"
							onClick={onReset}
							className="rounded-md px-1.5 py-1 font-medium text-content-muted hover:bg-muted hover:text-content"
						>
							Reset to default
						</button>
						<button
							type="button"
							onClick={() =>
								onChange([
									...new Set([
										...shown,
										...columns.map((c) => c.key),
									]),
								])
							}
							className="rounded-md px-1.5 py-1 font-medium text-content-muted hover:bg-muted hover:text-content"
						>
							Show all
						</button>
					</div>
				</div>
			)}
		</div>
	);
};
