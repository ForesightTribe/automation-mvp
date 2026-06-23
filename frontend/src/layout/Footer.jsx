/** Slim app footer. */
export const Footer = () => {
	return (
		<footer className="flex h-10 shrink-0 items-center justify-between border-t border-border bg-card px-6 text-xs text-content-subtle">
			<span>Foresight</span>
			<span>© {new Date().getFullYear()}</span>
		</footer>
	);
};
