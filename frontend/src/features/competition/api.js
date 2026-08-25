import { api } from "../../lib/axios";

/**
 * Competition endpoints (public scrape data, watchlist-scoped to the client's own
 * brand). All under /clients/{clientId}/competition. These take the reporting
 * window as ?start=&end= (the public scrapes are weekly, so a wider window = more weekly
 * points); optional ?keyword=/?city=/comma-separated ?marketplaces= (omitted = all)
 * narrow the slice. Each response carries an `as_of` timestamp for the freshness badge.
 */
const params = ({ start, end, marketplaces, ...rest } = {}) => ({
	start,
	end,
	marketplaces: marketplaces?.length ? marketplaces.join(",") : undefined,
	...rest,
});

export const getShareOfVoice = (clientId, opts) =>
	api.get(`/clients/${clientId}/competition/share-of-voice`, { params: params(opts) });

export const getRankMatrix = (clientId, opts) =>
	api.get(`/clients/${clientId}/competition/rank-matrix`, { params: params(opts) });

export const getTopCompetitors = (clientId, opts) =>
	api.get(`/clients/${clientId}/competition/top-competitors`, { params: params(opts) });

export const getPricePosition = (clientId, opts) =>
	api.get(`/clients/${clientId}/competition/price-position`, { params: params(opts) });
