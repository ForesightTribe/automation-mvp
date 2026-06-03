import client from "./client";

export const getOverview = (platform) =>
  client.get("/analytics/overview", { params: { platform } });

export const getRevenue = (platform, days) =>
  client.get("/analytics/revenue", { params: { platform, days } });
