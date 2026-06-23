import { ErrorBoundary as ReactErrorBoundary } from "react-error-boundary";
import { ErrorState } from "./ErrorState";
import { logger } from "../../lib/logger";

/**
 * Catches *render-time* crashes in the subtree and shows a fallback instead of
 * a blank screen. Wraps `react-error-boundary` so we keep a functional API (no
 * hand-written class) while still getting React's error lifecycle.
 *
 * Note: render errors only. API/network errors are handled by the axios client
 * + React Query and surfaced via <ErrorState> inside each feature.
 */
const Fallback = ({ error, resetErrorBoundary }) => (
	<ErrorState
		title="Something went wrong"
		message={error.message}
		onRetry={resetErrorBoundary}
	/>
);

export const ErrorBoundary = ({ children }) => (
	<ReactErrorBoundary
		FallbackComponent={Fallback}
		onError={(error, info) =>
			logger.error("render crash", error, info?.componentStack)
		}
	>
		{children}
	</ReactErrorBoundary>
);
