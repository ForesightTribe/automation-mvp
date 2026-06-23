/**
 * Inline error panel for a failed section/fetch. Pair with React Query's
 * `error` (an ApiError): pass `error.message` and `refetch` as `onRetry`.
 */
export const ErrorState = ({
	title = "Couldn't load this",
	message,
	onRetry,
}) => {
	return (
		<div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-danger-soft bg-danger-soft/40 p-8 text-center">
			<p className="font-display text-base font-semibold text-danger">
				{title}
			</p>
			{message && (
				<p className="max-w-md text-sm text-content-muted">{message}</p>
			)}
			{onRetry && (
				<button
					type="button"
					onClick={onRetry}
					className="mt-1 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-content hover:bg-muted"
				>
					Try again
				</button>
			)}
		</div>
	);
};
