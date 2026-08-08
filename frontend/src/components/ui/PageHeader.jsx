/**
 * Standard page heading: uppercase title, supporting line, optional right-hand
 * actions (export button, freshness badge, …). Every page uses this so the
 * typography stays in one place — restyle headings here, not per feature.
 */
export const PageHeader = ({ title, subtitle, actions }) => (
	<div className="flex flex-wrap items-start justify-between gap-3">
		<div>
			<h1 className="font-display text-xl font-bold tracking-tight text-content uppercase xl:text-2xl">
				{title}
			</h1>
			{subtitle && (
				<p className="mt-1 text-sm text-content-muted">{subtitle}</p>
			)}
		</div>
		{actions}
	</div>
);
