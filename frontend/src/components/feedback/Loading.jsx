/** Spinner + optional label for the first load of a section (isLoading). */
export const Loading = ({ label = "Loading…", className = "" }) => {
	return (
		<div
			className={`flex items-center justify-center gap-3 p-8 text-content-muted ${className}`}
		>
			<span
				className="size-5 animate-spin rounded-full border-2 border-border border-t-primary"
				aria-hidden="true"
			/>
			<span className="text-sm">{label}</span>
		</div>
	);
};
