import client from "./client";

export const listProducts = (platform, params) =>
  client.get("/products", { params: { platform, ...params } });

export const getProduct = (productId) =>
  client.get(`/products/${productId}`);
