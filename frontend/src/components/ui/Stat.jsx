/**
 * The two blocks a detail panel is built from.
 *
 * A headline figure with a small-caps label, and a titled section with an optional
 * right-aligned hint. Every campaign drawer in the product is built from these two.
 * Nothing here knows what it is describing, which is why it can live in `ui`.
 */
export const Stat = ({ label, value }) => (
	<div className="bg-card px-4 py-3">
		<p className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
			{label}
		</p>
		<p className="mt-1 font-display text-lg font-semibold text-content tabular-nums">
			{value}
		</p>
	</div>
);

export const Section = ({ title, hint, children }) => (
	<section className="mb-6 last:mb-0">
		<div className="mb-2 flex items-baseline justify-between gap-3">
			<h3 className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
				{title}
			</h3>
			{hint && (
				<span className="text-[11px] text-content-subtle">{hint}</span>
			)}
		</div>
		{children}
	</section>
);
