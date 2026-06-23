/**
 * Surface panel used across the dashboard (KPI tiles, chart wrappers, tables).
 * Compose with `title`/`actions` for a standard header, or pass raw children.
 */
export const Card = ({ title, actions, className = "", children }) => {
	return (
		<section
			className={`rounded-xl border border-border bg-card p-5 ${className}`}
		>
			{(title || actions) && (
				<header className="mb-4 flex items-center justify-between gap-3">
					{title && (
						<h2 className="font-display text-sm font-semibold text-content">
							{title}
						</h2>
					)}
					{actions}
				</header>
			)}
			{children}
		</section>
	);
};
