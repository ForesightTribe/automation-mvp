import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { useInsights } from "../hooks";
import { useDismissed } from "../dismissed";
import { AttentionRow } from "./AttentionRow";
import { InsightPanel } from "./InsightPanel";
import { Loading } from "../../../components/feedback/Loading";
import { ErrorState } from "../../../components/feedback/ErrorState";

/**
 * What needs attention, reached from the bar rather than from the page.
 *
 * In the bar because it is not a fact about the Overview — it is a fact about
 * the account, and it should be the same three clicks away whichever screen the
 * reader is on.
 *
 * Ranked by the API, money first; nothing is re-sorted here, so the order on
 * screen is the order the API can explain. What the automations did sits pinned
 * below the problems rather than competing with them for a rank.
 */
export const NotificationBell = () => {
	const { data, isLoading, error, refetch } = useInsights();
	const [open, setOpen] = useState(false);
	const [explaining, setExplaining] = useState(null);
	const wrap = useRef(null);

	useEffect(() => {
		if (!open) return;
		const onDown = (e) => {
			if (!wrap.current?.contains(e.target)) setOpen(false);
		};
		const onEsc = (e) => e.key === "Escape" && setOpen(false);
		document.addEventListener("mousedown", onDown);
		document.addEventListener("keydown", onEsc);
		return () => {
			document.removeEventListener("mousedown", onDown);
			document.removeEventListener("keydown", onEsc);
		};
	}, [open]);

	const { isDismissed, dismiss, dismissAll, restoreAll } = useDismissed();

	const everything = data ?? [];
	const all = everything.filter((i) => !isDismissed(i));
	const hidden = everything.length - all.length;
	const activity = all.find((i) => i.type === "change");
	const problems = all.filter((i) => i !== activity);

	return (
		<div ref={wrap} className="relative">
			<button
				type="button"
				onClick={() => setOpen((o) => !o)}
				aria-haspopup="menu"
				aria-expanded={open}
				aria-label={
					problems.length
						? `${problems.length} things need attention`
						: "Nothing needs attention"
				}
				title="Needs attention"
				className={`relative flex h-8 w-8 items-center justify-center rounded-full border transition-colors ${
					open
						? "border-content-subtle bg-inverse text-on-inverse"
						: "border-border bg-card text-content-muted hover:border-content-subtle hover:text-content"
				}`}
			>
				<Bell size={16} strokeWidth={1.75} />
				{/* A dot, not a count: the number is in the panel, and a badge of
				    digits on a 32px control is unreadable anyway. */}
				{problems.length > 0 && !open && (
					<span
						aria-hidden
						className="absolute top-1 right-1 h-2 w-2 rounded-full bg-warning ring-2 ring-card"
					/>
				)}
			</button>

			{open && (
				<div
					role="menu"
					className="absolute right-0 z-50 mt-2 flex max-h-[26rem] w-[24rem] flex-col rounded-xl border border-border bg-card shadow-xl"
				>
					<div className="flex items-baseline gap-3 px-4 pt-3.5 pb-2">
						<p className="flex-1 font-display text-sm font-semibold text-content">
							Needs attention
						</p>
						{all.length > 0 && (
							<button
								type="button"
								onClick={() => dismissAll(all)}
								className="text-[11px] font-medium text-content-subtle transition-colors hover:text-content"
							>
								Clear all
							</button>
						)}
					</div>

					<div className="flex min-h-0 flex-1 flex-col px-2 pb-2">
						{isLoading && <Loading label="Checking…" />}
						{error && (
							<ErrorState
								message={error.message}
								onRetry={refetch}
							/>
						)}

						{/* An empty list is a real answer, not a state to apologise for. */}
						{!isLoading && !error && all.length === 0 && (
							<p className="px-2 py-6 text-center text-sm text-content-muted">
								{hidden > 0
									? "Everything here has been dismissed."
									: "Nothing needs attention right now."}
							</p>
						)}

						{problems.length > 0 && (
							<ul className="flex flex-col divide-y divide-border overflow-y-auto">
								{problems.map((insight) => (
									<AttentionRow
										key={insight.id}
										insight={insight}
										onOpen={(i) => {
											setExplaining(i);
											setOpen(false);
										}}
										onDismiss={dismiss}
									/>
								))}
							</ul>
						)}

						{activity && (
							<ul className="mt-1 flex shrink-0 flex-col border-t border-border pt-1">
								<AttentionRow
									insight={activity}
									onOpen={(i) => {
										setExplaining(i);
										setOpen(false);
									}}
									onDismiss={dismiss}
								/>
							</ul>
						)}

						{hidden > 0 && (
							<button
								type="button"
								onClick={restoreAll}
								className="mt-1 shrink-0 border-t border-border px-2 py-2 text-left text-[11px] font-medium text-content-subtle transition-colors hover:text-content"
							>
								Show {hidden} dismissed
							</button>
						)}
					</div>
				</div>
			)}

			<InsightPanel
				insight={explaining}
				onClose={() => setExplaining(null)}
			/>
		</div>
	);
};
