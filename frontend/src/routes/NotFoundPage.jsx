import { Link } from "react-router-dom";

/** 404 fallback. */
export const NotFoundPage = () => {
	return (
		<div className="flex h-screen flex-col items-center justify-center gap-3 text-center">
			<p className="font-display text-4xl font-bold text-content">404</p>
			<p className="text-sm text-content-muted">
				This page doesn't exist.
			</p>
			<Link
				to="/"
				className="text-sm font-medium text-primary hover:underline"
			>
				Back to overview
			</Link>
		</div>
	);
};
