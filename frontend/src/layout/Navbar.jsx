import { DateRangePicker } from "./DateRangePicker";
import { MarketplacePills } from "./MarketplacePills";
import { ProfileMenu } from "./ProfileMenu";
import { ClientBadge } from "./ClientBadge";

/**
 * Top bar, spanning the column beside the rail: which marketplaces (left), over
 * what dates, then the brand and the account (right).
 *
 * The brand leads, because everything else on the bar is read against it: these
 * marketplaces, over these dates, FOR THIS BRAND. The account sits alone at the
 * right end. The rail keeps only the product mark and the nav.
 *
 * Brand and marketplaces lead on the left; the window sits just right of centre, and
 * the account alone on the right.
 *
 * The 2:1 flex ratio on the flanks is what places the window. `justify-between`
 * alone would let it drift every time the brand name or the marketplace row changed
 * width, which is the sort of movement you notice without being able to say why.
 *
 * Responsive: one row on laptop, wraps to two on tablet. The row height grows with
 * `min-h` rather than being fixed.
 */
export const Navbar = () => (
	<header className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-card px-4 py-2 lg:px-6 xl:px-8 2xl:px-10">
		{/* A wide gap, not the usual one: the brand and the marketplaces are two
		    different questions sitting side by side, and at a normal control spacing
		    they read as one long strip of chips. */}
		<div className="flex flex-[2] basis-0 items-center gap-6 lg:gap-8">
			<ClientBadge />
			<MarketplacePills />
		</div>

		<DateRangePicker />

		<div className="flex flex-1 basis-0 items-center justify-end">
			<ProfileMenu />
		</div>
	</header>
);
