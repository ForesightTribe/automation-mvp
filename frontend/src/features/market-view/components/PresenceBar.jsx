/** A share as a bar plus the number — the bar is for scanning a column fast. */
export const PresenceBar = ({ pct }) => {
	if (pct == null) return <span className="text-content-subtle">—</span>;
	const tone =
		pct >= 90 ? "bg-success" : pct >= 60 ? "bg-warning" : "bg-danger";
	return (
		<span className="flex items-center gap-2">
			<span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
				<span
					className={`block h-full rounded-full ${tone}`}
					style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
				/>
			</span>
			<span className="text-xs tabular-nums text-content-muted">
				{pct.toFixed(1)}%
			</span>
		</span>
	);
};
