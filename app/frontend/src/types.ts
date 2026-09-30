export type RiskBand = "high" | "medium" | "low";

export type ActionType =
  | "reconfirmed"
  | "deposit_requested"
  | "overbooked_backup"
  | "released"
  | "note";

export const ACTION_TYPES: ActionType[] = [
  "reconfirmed",
  "deposit_requested",
  "overbooked_backup",
  "released",
  "note",
];

export interface Reservation {
  reservation_id: string;
  hotel: string;
  arrival_date: string;
  lead_time: number;
  adr: number;
  market_segment: string;
  adults: number;
  children: number;
  babies: number;
  deposit_type: string;
  customer_type: string;
  cancel_probability: number;
  risk_band: RiskBand;
  model_version: string | number;
  scored_at: string;
}

export interface Action {
  id: number;
  reservation_id: string;
  action_type: ActionType;
  note: string | null;
  acted_by: string | null;
  acted_at: string;
}

export interface Kpis {
  total: number;
  high_risk: number;
  medium_risk: number;
  low_risk: number;
  avg_cancel_probability: number | null;
  risk_band_mix: { risk_band: RiskBand; count: number }[];
}

export interface ReservationsPage {
  total: number;
  limit: number;
  offset: number;
  items: Reservation[];
}

export interface ReservationDetail {
  reservation: Reservation;
  actions: Action[];
}

export interface Filters {
  hotel?: string;
  risk_band?: RiskBand;
  market_segment?: string;
  min_lead_time?: number;
}
