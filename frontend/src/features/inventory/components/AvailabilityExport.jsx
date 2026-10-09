import { useState } from "react";
import { ExportButton } from "../../../components/ui/ExportButton";
import { downloadCsv, exportName } from "../../../lib/exportTable";
import { useDateRange } from "../../../context/DateRangeContext";
import {
	useCities,
	useDistribution,
	useStores,
	useAvailabilityHistory,
	usePricing,
} from "../hooks";
import {
	citySection,
	storeSection,
	productSection,
	historySection,
	pricingSection,
} from "../exportSections";

/**
 * The whole Availability page as one workbook — every section, in the order they
 * appear on screen. Each card also exports its own section on its own.
 *
 * Everything here is already loaded for the page, so the file costs no extra
 * request and the figures are the ones on screen.
 */
export const AvailabilityExport = ({ kind }) => {
	const { range } = useDateRange();
	const [busy, setBusy] = useState(false);

	const cities = useCities(kind);
	const stores = useStores({ kind });
	const products = useDistribution(kind);
	const history = useAvailabilityHistory(kind);
	const pricing = usePricing(kind);

	const sections = () =>
		[
			citySection(cities.data, kind),
			storeSection(stores.data, kind),
			productSection(products.data, stores.data, kind),
			historySection(history.data),
			pricingSection(pricing.data),
		].filter(Boolean);

	const ready = !cities.isLoading && !stores.isLoading && !products.isLoading;

	const onExport = async () => {
		setBusy(true);
		try {
			downloadCsv(exportName(`availability-${kind}`, range), sections());
		} finally {
			setBusy(false);
		}
	};

	return (
		<ExportButton
			onExport={onExport}
			busy={busy}
			disabled={!ready}
			label="Export page"
		/>
	);
};
