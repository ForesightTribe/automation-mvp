/**
 * Base button. Domain-agnostic UI primitive — lives in components/ui, owned by
 * no feature. Variants map to the theme tokens in index.css.
 */
const VARIANTS = {
	primary: "bg-primary text-on-primary hover:bg-primary-hover",
	secondary: "border border-border bg-card text-content hover:bg-muted",
	/* Brand-led action (outlined MIRA red) — the shell's Log out, not a general
	   primary action. Use `primary` for those. */
	/* Outlined at rest, FILLED on hover. Inverting to solid brand with white text is
	   unmistakable at a glance and matches the solid variant it escalates into; a tinted
	   wash under red text reads as the same button whether the pointer is on it or not. */
	brand: "border border-brand bg-card text-brand hover:bg-brand hover:text-on-brand hover:shadow-sm active:translate-y-px",
	/* Solid brand — the one obvious action on a screen. Deepens on hover and presses
	   down on click, so the control feels answerable rather than painted on. */
	brandSolid:
		"bg-brand text-on-brand shadow-sm hover:bg-brand-hover hover:shadow active:translate-y-px",
	danger: "bg-danger text-on-primary hover:opacity-90",
	ghost: "text-content hover:bg-muted",
};

const SIZES = {
	xs: "px-2.5 py-1 text-[10px]",
	sm: "px-2.5 py-1 text-xs",
	md: "px-3.5 py-2 text-sm",
	lg: "px-5 py-2.5 text-base",
};

export const Button = ({
	variant = "primary",
	size = "md",
	type = "button",
	className = "",
	disabled,
	children,
	...props
}) => {
	return (
		<button
			type={type}
			disabled={disabled}
			className={`inline-flex items-center justify-center gap-2 rounded-md font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
			{...props}
		>
			{children}
		</button>
	);
};
