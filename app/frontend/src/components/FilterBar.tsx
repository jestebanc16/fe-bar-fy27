import type { Filters, RiskBand } from "../types";

interface Props {
  filters: Filters;
  onChange: (next: Filters) => void;
}

const RISK_BANDS: RiskBand[] = ["high", "medium", "low"];

export default function FilterBar({ filters, onChange }: Props) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  const inputCls =
    "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900";
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
        Hotel
        <select
          className={inputCls}
          value={filters.hotel ?? ""}
          onChange={(e) => set({ hotel: e.target.value || undefined })}
        >
          <option value="">All</option>
          <option value="City Hotel">City Hotel</option>
          <option value="Resort Hotel">Resort Hotel</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
        Risk band
        <select
          className={inputCls}
          value={filters.risk_band ?? ""}
          onChange={(e) =>
            set({ risk_band: (e.target.value || undefined) as RiskBand | undefined })
          }
        >
          <option value="">All</option>
          {RISK_BANDS.map((b) => (
            <option key={b} value={b} className="capitalize">
              {b}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
        Market segment
        <input
          className={inputCls}
          placeholder="e.g. Online TA"
          value={filters.market_segment ?? ""}
          onChange={(e) => set({ market_segment: e.target.value || undefined })}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
        Min lead time (days)
        <input
          type="number"
          min={0}
          className={`${inputCls} w-32`}
          value={filters.min_lead_time ?? ""}
          onChange={(e) =>
            set({
              min_lead_time: e.target.value ? Number(e.target.value) : undefined,
            })
          }
        />
      </label>
      <button
        type="button"
        onClick={() => onChange({})}
        className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        Clear
      </button>
    </div>
  );
}
