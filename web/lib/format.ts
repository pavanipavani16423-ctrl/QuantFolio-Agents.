export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const s = (value * 100).toFixed(digits);
  return value > 0 ? `+${s}%` : `${s}%`;
}

export function money(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined) return "–";
  // Indian rupees use Indian digit grouping (₹49,95,594)
  return value.toLocaleString(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  if (value < 60) return `${value.toFixed(1)} s`;
  return `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`;
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return value.toFixed(digits);
}

export function ago(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
