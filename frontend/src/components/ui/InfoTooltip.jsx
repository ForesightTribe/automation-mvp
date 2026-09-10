import { Info } from "lucide-react";
import { HoverHint } from "./HoverHint";

/**
 * The "what does this actually mean" affordance next to a card title: a visible ⓘ that
 * opens the shared hover panel.
 *
 * Use this where the explanation needs advertising (a KPI tile, a section heading). Where a
 * whole row of labels would each need one, use HoverHint directly instead: fourteen icons
 * across a table header is noise, and the header itself is a large enough target.
 */
export const InfoTooltip = ({ label, className = "" }) => (
	<HoverHint label={label} className={className}>
		{/* A real icon at 15px in muted ink, not a hairline circle with a lowercase i: at
		    11px inside an uppercase label the old one was invisible in practice, and an
		    affordance nobody sees is the same as one that is missing. */}
		<button
			type="button"
			aria-label={`About this metric: ${label}`}
			className="flex items-center justify-center rounded-full text-content-muted transition-colors hover:text-brand"
		>
			<Info size={15} strokeWidth={2} />
		</button>
	</HoverHint>
);
