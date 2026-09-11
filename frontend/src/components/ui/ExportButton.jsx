import { Download, FileSpreadsheet } from "lucide-react";

/**
 * Downloads what the table is showing, as CSV. Disabled while there is nothing to
 * download.
 *
 * Shared, because "export this table" is not one feature's idea: Insights and the
 * automation logs both offer it, and two buttons that do the same job should not be
 * two buttons.
 */
export const ExportButton = ({
	onExport,
	busy,
	disabled,
	label = "Export",
	busyLabel = "Preparing…",
}) => (
	<>
		{/* At rest it is a quiet utility beside a table, with the spreadsheet mark carrying the
		    only colour. On hover it fills with Excel's own green and everything inside turns
		    white, so the association with the file it produces is unmistakable at the moment
		    of the click.

		    ⚠️ #217346 is Microsoft's green, not ours, which is why it is a literal rather than
		    a token. `--color-success` means "this went well" in this system and is reserved
		    for that; borrowing it here would make a download read as a status. */}
		<button
			type="button"
			onClick={onExport}
			disabled={busy || disabled}
			className="group/dl flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-content transition-colors hover:border-[#217346] hover:bg-[#217346] hover:text-white disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-border disabled:hover:bg-card disabled:hover:text-content"
		>
			<FileSpreadsheet
				size={14}
				className="text-[#217346] group-hover/dl:text-white group-disabled/dl:text-[#217346]"
			/>
			{busy ? busyLabel : label}
			<Download size={13} className="opacity-70" />
		</button>
	</>
);
