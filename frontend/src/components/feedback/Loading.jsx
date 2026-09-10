/**
 * First-load indicator for a section.
 *
 * Three dots rising in sequence rather than a spinning ring. A ring turning at a constant
 * rate says nothing except "busy", and on this dashboard some sections wait a minute or
 * more, where a steady spin starts to read as a hang. A sequence has a beat, so the eye can
 * see it is still going without staring at it.
 *
 * Brand-coloured, and the dots carry the only colour: this is a state, not an action, so it
 * should not compete with the controls around it.
 */
const DOT =
	"inline-block size-1.5 rounded-full bg-brand [animation:loading-bob_1.05s_ease-in-out_infinite]";

export const Loading = ({ label = "Loading…", className = "" }) => (
	<div
		role="status"
		aria-live="polite"
		className={`flex items-center justify-center gap-3 p-8 text-content-muted ${className}`}
	>
		<span className="flex items-end gap-1" aria-hidden="true">
			<span className={DOT} />
			<span className={`${DOT} [animation-delay:0.14s]`} />
			<span className={`${DOT} [animation-delay:0.28s]`} />
		</span>
		<span className="text-sm">{label}</span>
	</div>
);
