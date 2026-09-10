import { useState } from "react";

/**
 * A workbook on screen: one scrolling data pane with its sheet tabs underneath.
 *
 * Reports of this shape are several tables that belong together, and stacking
 * them down the page means scrolling back up every time you want the other one.
 * Excel solved this with tabs at the bottom, and since these reports ARE that
 * workbook, borrowing the pattern costs nothing to explain.
 *
 * The pane is a fixed height that scrolls in both directions, so the tab strip
 * stays put and the page around it does not move as you switch sheets.
 *
 * `sheets` is [{ key, label, note?, render(active) }]. `render` is a thunk so
 * only the visible sheet's rows are built, and it receives `active` so a sheet
 * that has to FETCH its rows can hold off until someone opens it. A workbook
 * should not pay to load a sheet nobody is looking at.
 */
export const WorkbookView = ({ sheets, height = "62vh", footer }) => {
	const [active, setActive] = useState(sheets[0]?.key);
	const sheet = sheets.find((s) => s.key === active) ?? sheets[0];

	return (
		<div className="flex flex-col overflow-hidden rounded-lg border border-border bg-card">
			<div className="overflow-auto" style={{ height }}>
				{sheet?.render(true)}
			</div>

			{sheet?.note && (
				<p className="border-t border-border bg-surface px-3 py-2 text-[11px] leading-relaxed text-content-subtle">
					{sheet.note}
				</p>
			)}

			{/* The tab strip sits on the surface tone, so it reads as the frame around the
			    sheet rather than as another row of it. */}
			<div className="flex items-center gap-1 border-t border-border bg-surface px-2 py-1.5">
				{sheets.map((s) => (
					<button
						key={s.key}
						type="button"
						aria-current={s.key === sheet?.key ? "page" : undefined}
						onClick={() => setActive(s.key)}
						className={`rounded-md px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-colors ${
							s.key === sheet?.key
								? "bg-card text-content shadow-sm"
								: "text-content-muted hover:bg-muted hover:text-content"
						}`}
					>
						{s.label}
					</button>
				))}
				{footer && (
					<div className="ml-auto flex items-center gap-2 pr-1">
						{footer}
					</div>
				)}
			</div>
		</div>
	);
};
