import { Info } from "lucide-react";
import { HoverHint } from "../../../components/ui/HoverHint";

/**
 * One labelled form field, used for every field in the wizard.
 *
 * It exists so the wizard has ONE answer to "how does a field look": the same label weight,
 * the same spacing, and the same place for its explanation. Before this, some fields carried
 * a paragraph of grey text underneath and others carried nothing, so the form read as
 * several forms.
 *
 * ⚠️ Explanations go in `hint`, never under the input. A sentence like "what the campaign
 * runs at whenever no scheduled window is open" is read once and then re-read forever, and
 * it pushes the next field down the page every time. The ⓘ holds it instead: it sits clear
 * of the label with its own gap and a slight drop, so it reads as a marker beside the words
 * rather than punctuation jammed against them.
 *
 * `note` is for the rare line that must be SEEN rather than sought, such as a warning that
 * the value being typed changes something the reader did not come here to change.
 */
export const Field = ({
	label,
	hint,
	note,
	noteTone = "subtle",
	htmlFor,
	className = "",
	children,
}) => (
	<div className={`flex flex-col ${className}`}>
		<div className="mb-1.5 flex items-center gap-2">
			<label
				htmlFor={htmlFor}
				className="text-xs font-medium text-content"
			>
				{label}
			</label>
			{hint && (
				<HoverHint label={hint}>
					<span className="flex translate-y-px cursor-help items-center text-content-subtle transition-colors hover:text-content">
						<Info size={13} />
					</span>
				</HoverHint>
			)}
		</div>
		{children}
		{note && (
			<p
				className={`mt-1.5 text-[11px] leading-relaxed ${
					noteTone === "warn" ? "text-warning" : "text-content-subtle"
				}`}
			>
				{note}
			</p>
		)}
	</div>
);

/** The one input treatment. Neutral on focus: brand red on a text box reads as a rejection. */
export const FIELD_INPUT =
	"rounded-md border border-border bg-card px-3 py-2 text-sm text-content transition-colors focus:border-content focus:outline-none disabled:bg-muted disabled:text-content-subtle";

/** A section heading inside a step, above a group of fields. */
export const FieldGroupTitle = ({ children }) => (
	<p className="text-[11px] font-semibold tracking-[0.12em] text-content-subtle uppercase">
		{children}
	</p>
);
