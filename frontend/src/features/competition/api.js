import { api } from "../../lib/axios";

/**
 * Competition endpoints (public scrape data, watchlist-scoped to the client's own
 * brand). All under /clients/{clientId}/competition. These take the reporting
 * window as ?days= (the public scrapes are weekly, so a wider window = more weekly
 * points); optional ?keyword=/?city=/?marketplace= narrow the slice. Each response
 * carries an `as_of` timestamp for the freshness badge.
 */
export const getShareOfVoice = (clientId, { days, keyword, city, marketplace } = {}) =>
	api.get(`/clients/${clientId}/competition/share-of-voice`, {
		params: { days, keyword, city, marketplace },
	});

export const getRankMatrix = (clientId, { days, marketplace } = {}) =>
	api.get(`/clients/${clientId}/competition/rank-matrix`, {
		params: { days, marketplace },
	});

export const getTopCompetitors = (
	clientId,
	{ days, keyword, city, marketplace, limit } = {},
) =>
	api.get(`/clients/${clientId}/competition/top-competitors`, {
		params: { days, keyword, city, marketplace, limit },
	});

export const getPricePosition = (
	clientId,
	{ days, keyword, city, marketplace, kind } = {},
) =>
	api.get(`/clients/${clientId}/competition/price-position`, {
		params: { days, keyword, city, marketplace, kind },
	});
