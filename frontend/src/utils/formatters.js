export const formatCurrency = (amount) => {
  if (amount === null || amount === undefined) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
};

export const formatNumber = (num) => {
  if (num === null || num === undefined) return "—";
  if (num >= 10_000_000) return `${(num / 10_000_000).toFixed(2)}Cr`;
  if (num >= 100_000)    return `${(num / 100_000).toFixed(2)}L`;
  if (num >= 1_000)      return `${(num / 1_000).toFixed(1)}K`;
  return String(num);
};

export const formatPercent = (value, decimals = 2) => {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(decimals)}%`;
};

export const formatDate = (dateStr) => {
  if (!dateStr) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(dateStr));
};

export const formatROAS = (value) => {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(2)}x`;
};
