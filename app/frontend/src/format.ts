import type { RiskBand } from "./types";

export const pct = (x: number | null | undefined) =>
  x === null || x === undefined ? "—" : `${(x * 100).toFixed(1)}%`;

export const money = (x: number | null | undefined) =>
  x === null || x === undefined
    ? "—"
    : x.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      });

export const riskBadgeClasses: Record<RiskBand, string> = {
  high: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  low: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
};
