import logoMark from "../assets/brand/logo-mark.png";

/**
 * The Foresight brand mark + wordmark. The mark is an image asset (see
 * src/assets/brand) so design can replace the file without touching this
 * component; the wordmark stays as text so it inherits the brand face and
 * `--color-brand`.
 *
 * Kept small: the mark is 24px and the wordmark steps down to match, so the rail's
 * corner is a label rather than a banner.
 *
 * `showWordmark={false}` leaves the mark alone, for the collapsed rail where there
 * is no room for the word and the mark alone still reads as the product.

 */
export const Logo = ({ showWordmark = true, size = "sm" }) => (
	<div className="flex shrink-0 items-center gap-2">
		<img
			src={logoMark}
			alt="Foresight"
			className={`${size === "lg" ? "h-8" : "h-6"} w-auto`}
		/>
		{showWordmark && (
			<span
				className={`font-display font-bold tracking-tight text-brand ${
					size === "lg" ? "text-2xl" : "text-lg"
				}`}
			>
				Foresight
			</span>
		)}
	</div>
);
