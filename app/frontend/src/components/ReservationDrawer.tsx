import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import toast from "react-hot-toast";
import { api } from "../api";
import type { ReservationDetail } from "../types";
import { money, pct } from "../format";
import RiskBadge from "./RiskBadge";
import ActionForm from "./ActionForm";

interface Props {
  reservationId: string;
  onClose: () => void;
  onActed: () => void;
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}

export default function ReservationDrawer({ reservationId, onClose, onActed }: Props) {
  const [detail, setDetail] = useState<ReservationDetail | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .reservation(reservationId)
      .then(setDetail)
      .catch((e) => toast.error(`Detail: ${e.message}`))
      .finally(() => setLoading(false));
  }, [reservationId]);

  useEffect(() => {
    load();
  }, [load]);

  const onCreated = () => {
    load();
    onActed();
  };

  const r = detail?.reservation;

  return (
    <div className="fixed inset-0 z-30">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <aside className="absolute inset-0 flex flex-col bg-white shadow-xl dark:bg-slate-900 sm:inset-y-0 sm:right-0 sm:left-auto sm:w-full sm:max-w-md">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 className="text-sm font-semibold">Reservation detail</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-4 py-4">
          {loading && (
            <div className="h-40 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
          )}

          {r && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-slate-500">{r.reservation_id}</span>
                <RiskBadge band={r.risk_band} />
              </div>
              <dl className="grid grid-cols-2 gap-3">
                <Fact label="Hotel" value={r.hotel} />
                <Fact label="Arrival" value={r.arrival_date} />
                <Fact label="Cancel probability" value={pct(r.cancel_probability)} />
                <Fact label="Lead time (days)" value={r.lead_time} />
                <Fact label="ADR" value={money(r.adr)} />
                <Fact label="Market segment" value={r.market_segment} />
                <Fact label="Customer type" value={r.customer_type} />
                <Fact label="Deposit type" value={r.deposit_type} />
                <Fact label="Party (A/C/B)" value={`${r.adults}/${r.children}/${r.babies}`} />
                <Fact label="Model version" value={String(r.model_version)} />
              </dl>

              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Record an action
                </h3>
                <ActionForm reservationId={r.reservation_id} onCreated={onCreated} />
              </div>

              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Prior actions
                </h3>
                {detail!.actions.length === 0 ? (
                  <p className="text-sm text-slate-500">No actions recorded yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {detail!.actions.map((a) => (
                      <li
                        key={a.id}
                        className="rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-800"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium capitalize">
                            {a.action_type.replace(/_/g, " ")}
                          </span>
                          <span className="text-xs text-slate-400">
                            {new Date(a.acted_at).toLocaleString()}
                          </span>
                        </div>
                        {a.note && <p className="mt-1 text-slate-600 dark:text-slate-300">{a.note}</p>}
                        {a.acted_by && (
                          <p className="mt-1 text-xs text-slate-400">by {a.acted_by}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
