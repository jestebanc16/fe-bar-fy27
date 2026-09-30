import type { Kpis } from "../types";
import { pct } from "../format";

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export default function KpiCards({ kpis }: { kpis: Kpis | null }) {
  if (!kpis) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
          />
        ))}
      </div>
    );
  }
  const max = Math.max(kpis.high_risk, kpis.medium_risk, kpis.low_risk, 1);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card label="Scored reservations" value={kpis.total.toLocaleString()} />
        <Card label="High risk" value={kpis.high_risk.toLocaleString()} />
        <Card
          label="Avg cancel probability"
          value={pct(kpis.avg_cancel_probability)}
        />
        <Card
          label="Risk mix (H / M / L)"
          value={`${kpis.high_risk} / ${kpis.medium_risk} / ${kpis.low_risk}`}
          hint="model-scored snapshot"
        />
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Risk-band distribution
        </p>
        <div className="space-y-2">
          {kpis.risk_band_mix.map((b) => (
            <div key={b.risk_band} className="flex items-center gap-3">
              <span className="w-16 text-sm capitalize">{b.risk_band}</span>
              <div className="h-3 flex-1 overflow-hidden rounded bg-slate-100 dark:bg-slate-800">
                <div
                  className={
                    b.risk_band === "high"
                      ? "h-full bg-risk-high"
                      : b.risk_band === "medium"
                        ? "h-full bg-risk-medium"
                        : "h-full bg-risk-low"
                  }
                  style={{ width: `${(b.count / max) * 100}%` }}
                />
              </div>
              <span className="w-16 text-right text-sm tabular-nums">
                {b.count.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
