import { ExportButton } from "../../../components/ui/ExportButton";

/** A section's own download, on its own row above the card rather than in its header. */
export const SectionExport = ({ onExport, disabled }) => (
	<div className="mb-2 flex justify-end">
		<ExportButton onExport={onExport} disabled={disabled} />
	</div>
);
