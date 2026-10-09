import { api } from "../../lib/axios";

/**
 * Market View reads. All public-scrape data under /clients/{id}/competition —
 * the same endpoints the Competition page uses, viewed at store and keyword
 * grain rather than as national roll-ups.
 */
const params = ({ start, end, marketplaces, ...rest } = {}) => ({
	start,
	end,
	marketplaces: marketplaces?.length ? marketplaces.join(",") : undefined,
	...rest,
});

const base = (clientId) => `/clients/${clientId}/competition`;

export const getKeywordPresence = (clientId, opts) =>
	api.get(`${base(clientId)}/keyword-presence`, { params: params(opts) });

export const getSkuVariance = (clientId, opts) =>
	api.get(`${base(clientId)}/sku-variance`, { params: params(opts) });

export const getStoreCompetition = (clientId, opts) =>
	api.get(`${base(clientId)}/store-competition`, { params: params(opts) });


export const getBrandComparison = (clientId, opts) =>
	api.get(`${base(clientId)}/brand-comparison`, { params: params(opts) });
