import type { Reservation } from "../types";
import { money, pct } from "../format";
import RiskBadge from "./RiskBadge";

interface Props {
  items: Reservation[];
  loading: boolean;
  total: number;
  limit: number;
  offset: number;
  onSelect: (id: string) => void;
  onPage: (nextOffset: number) => void;
}

export default function ReservationsTable({
  items,
  loading,
  total,
  limit,
  offset,
  onSelect,
  onPage,
}: Props) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  const th =
    "px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400";
  const td = "px-3 py-2 text-sm";
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className={th}>Reservation</th>
              <th className={`${th} hidden sm:table-cell`}>Hotel</th>
              <th className={`${th} hidden md:table-cell`}>Arrival</th>
              <th className={`${th} hidden lg:table-cell`}>Lead</th>
              <th className={`${th} hidden lg:table-cell`}>ADR</th>
              <th className={`${th} hidden md:table-cell`}>Segment</th>
              <th className={th}>Cancel prob.</th>
              <th className={th}>Risk</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {loading &&
              items.length === 0 &&
              [0, 1, 2, 3, 4].map((i) => (
                <tr key={`sk-${i}`}>
                  <td className={td} colSpan={8}>
                    <div className="h-5 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
                  </td>
                </tr>
              ))}
            {!loading && items.length === 0 && (
              <tr>
                <td className={`${td} text-center text-slate-500`} colSpan={8}>
                  No reservations match these filters.
                </td>
              </tr>
            )}
            {items.map((r) => (
              <tr
                key={r.reservation_id}
                onClick={() => onSelect(r.reservation_id)}
                className="cursor-pointer transition hover:bg-slate-50 dark:hover:bg-slate-800/50"
              >
                <td className={`${td} font-mono text-xs`}>
                  {r.reservation_id.slice(0, 12)}…
                </td>
                <td className={`${td} hidden sm:table-cell`}>{r.hotel}</td>
                <td className={`${td} hidden md:table-cell`}>{r.arrival_date}</td>
                <td className={`${td} hidden lg:table-cell tabular-nums`}>{r.lead_time}</td>
                <td className={`${td} hidden lg:table-cell tabular-nums`}>{money(r.adr)}</td>
                <td className={`${td} hidden md:table-cell`}>{r.market_segment}</td>
                <td className={`${td} tabular-nums`}>{pct(r.cancel_probability)}</td>
                <td className={td}>
                  <RiskBadge band={r.risk_band} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-slate-200 px-3 py-2 text-sm dark:border-slate-800">
        <span className="text-slate-500 dark:text-slate-400">
          {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => onPage(Math.max(0, offset - limit))}
            className="rounded-lg border border-slate-200 px-3 py-1 disabled:opacity-40 dark:border-slate-700"
          >
            Prev
          </button>
          <button
            type="button"
            disabled={to >= total}
            onClick={() => onPage(offset + limit)}
            className="rounded-lg border border-slate-200 px-3 py-1 disabled:opacity-40 dark:border-slate-700"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
