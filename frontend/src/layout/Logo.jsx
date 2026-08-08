import logoMark from "../assets/brand/logo-mark.png";

/**
 * The Foresight brand mark + wordmark. The mark is an image asset (see
 * src/assets/brand) so design can replace the file without touching this
 * component; the wordmark stays as text so it inherits the brand face and
 * `--color-brand`.
 */
export const Logo = () => (
	<div className="flex shrink-0 items-center gap-2">
		<img src={logoMark} alt="" aria-hidden="true" className="h-7 w-auto" />
		<span className="font-display text-xl font-extrabold tracking-tight text-brand">
			Foresight
		</span>
	</div>
);
