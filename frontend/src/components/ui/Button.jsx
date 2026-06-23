/**
 * Base button. Domain-agnostic UI primitive — lives in components/ui, owned by
 * no feature. Variants map to the theme tokens in index.css.
 */
const VARIANTS = {
	primary: "bg-primary text-on-primary hover:bg-primary-hover",
	secondary: "border border-border bg-card text-content hover:bg-muted",
	danger: "bg-danger text-on-primary hover:opacity-90",
	ghost: "text-content hover:bg-muted",
};

const SIZES = {
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
			className={`inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
			{...props}
		>
			{children}
		</button>
	);
};
