import type {
  Action,
  ActionType,
  Filters,
  Kpis,
  ReservationDetail,
  ReservationsPage,
} from "./types";

const BASE = "/api";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function buildQuery(params: Filters & { limit?: number; offset?: number }): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  });
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  kpis: () => jsonFetch<Kpis>("/kpis"),
  reservations: (params: Filters & { limit?: number; offset?: number }) =>
    jsonFetch<ReservationsPage>(`/reservations${buildQuery(params)}`),
  reservation: (id: string) =>
    jsonFetch<ReservationDetail>(`/reservations/${encodeURIComponent(id)}`),
  createAction: (id: string, body: { action_type: ActionType; note?: string }) =>
    jsonFetch<Action>(`/reservations/${encodeURIComponent(id)}/actions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
