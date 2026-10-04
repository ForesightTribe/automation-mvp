import { Lock } from "lucide-react";

/**
 * Shown to members on pages whose write actions are admin-only. The backend is
 * the wall (every such write 403s); this only explains why the page is inert.
 */
export const ReadOnlyNotice = ({
	what = "Changes here are admin-only.",
}) => (
	<div className="flex items-start gap-2.5 rounded-xl border border-border bg-surface px-4 py-3">
		<Lock
			size={15}
			aria-hidden
			className="mt-0.5 shrink-0 text-content-muted"
		/>
		<p className="text-sm text-content-muted">
			<span className="font-medium text-content">View only.</span> {what}{" "}
			Ask an admin on your account to make changes.
		</p>
	</div>
);
