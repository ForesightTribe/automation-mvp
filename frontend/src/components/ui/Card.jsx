/**
 * Surface panel used across the dashboard (KPI tiles, chart wrappers, tables).
 * Compose with `title`/`actions` for a standard header, or pass raw children.
 */
export const Card = ({
	title,
	actions,
	className = "",
	titleClassName = "",
	children,
}) => {
	return (
		<section
			className={`rounded-xl border border-border bg-card p-5 shadow-[0_2px_8px_rgba(0,0,0,0.10)] ${className}`}
		>
			{(title || actions) && (
				<header className="mb-4 flex items-center justify-between gap-3">
					{title && (
						<h2
							className={`font-display text-sm font-semibold text-content lg:text-base ${titleClassName}`}
						>
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
