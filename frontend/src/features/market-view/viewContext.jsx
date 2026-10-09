import { createContext, useContext, useMemo, useState } from "react";

/**
 * What the page is currently looking at: one city (or all), and one keyword.
 *
 * The keyword is the spine. Picking a keyword in the visibility table narrows
 * the store explorer and the SKU table beneath it, which is how you get from
 * "this term is weak" to "these are the shops losing it" without changing page.
 */
const Ctx = createContext(null);

export const MarketViewProvider = ({ children }) => {
	const [city, setCity] = useState(null);
	const [keyword, setKeyword] = useState(null);

	const value = useMemo(
		() => ({ city, setCity, keyword, setKeyword }),
		[city, keyword],
	);
	return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
};

export const useMarketView = () => {
	const v = useContext(Ctx);
	if (!v) throw new Error("useMarketView must be used inside MarketViewProvider");
	return v;
};
