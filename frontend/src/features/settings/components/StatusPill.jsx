/**
 * Where one marketplace account stands: coming soon (no authenticator), not set up (no
 * login saved), not signed in (login saved, no live session), connected.
 */
export const StatusPill = ({ platform }) => {
	const [label, tone] = !platform.wired
		? ["Coming soon", "bg-muted text-content-subtle"]
		: platform.connected
			? ["Connected", "bg-success-soft text-success"]
			: platform.has_credentials
				? ["Not signed in", "bg-warning-soft text-warning"]
				: ["Not set up", "bg-muted text-content-subtle"];
	return (
		<span
			className={`rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${tone}`}
		>
			{label}
		</span>
	);
};
