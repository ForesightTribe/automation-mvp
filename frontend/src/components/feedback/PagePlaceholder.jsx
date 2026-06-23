/**
 * Temporary scaffold placeholder for feature pages not yet built. Delete each
 * usage as its real page lands.
 */
export const PagePlaceholder = ({ title, subtitle }) => {
	return (
		<div className="flex flex-col gap-6">
			<div>
				<h1 className="font-display text-xl font-bold text-content">
					{title}
				</h1>
				{subtitle && (
					<p className="text-sm text-content-muted">{subtitle}</p>
				)}
			</div>
			<div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-border bg-card text-sm text-content-subtle">
				Coming soon
			</div>
		</div>
	);
};
