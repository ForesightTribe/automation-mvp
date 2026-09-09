import { HoverHint } from "../../../components/ui/HoverHint";

/**
 * Small bordered tags ("Increase Budget to ₹750"). Point at one to see the rule behind it,
 * its window and what it reverts to, without opening Edit. Neutral ink, not brand red: the
 * pill summarises intent, it is not a status.
 *
 * The detail is a HoverHint rather than a click-to-open popover of its own. Reading a row
 * should not cost a click and then another to dismiss, and the shared hint already solves
 * the hard parts these pills need: it is `position: fixed`, so it escapes the table's
 * `overflow-auto` clip, it flips to whichever side has room, and it opens on focus as well
 * as hover so the pills stay reachable by keyboard.
 */
export const ActionsSummaryPills = ({ tags }) => (
	<div className="flex flex-wrap gap-1.5">
		{tags.map((tag, i) => (
			<HoverHint key={i} label={tag.detail} tabIndex={0}>
				<span className="cursor-default whitespace-nowrap rounded-full border border-border px-2.5 py-0.5 text-xs font-medium text-content-muted transition-colors hover:border-content-subtle hover:text-content">
					{tag.label}
				</span>
			</HoverHint>
		))}
	</div>
);
