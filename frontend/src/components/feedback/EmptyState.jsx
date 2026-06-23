/** Shown when a successful fetch returns no rows. */
export const EmptyState = ({
	title = "Nothing here yet",
	message,
	icon = "∅",
}) => {
	return (
		<div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-card p-10 text-center">
			<span className="text-2xl text-content-subtle">{icon}</span>
			<p className="font-display text-base font-medium text-content">
				{title}
			</p>
			{message && (
				<p className="max-w-md text-sm text-content-muted">{message}</p>
			)}
		</div>
	);
};
