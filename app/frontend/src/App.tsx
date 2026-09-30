import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";
import Header from "./components/Header";
import KpiCards from "./components/KpiCards";
import FilterBar from "./components/FilterBar";
import ReservationsTable from "./components/ReservationsTable";
import { api } from "./api";
import type { Filters, Kpis, ReservationsPage } from "./types";
import { useUI } from "./store";

const LIMIT = 50;

export default function App() {
  const theme = useUI((s) => s.theme);
  const setSelectedId = useUI((s) => s.setSelectedId);

  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [page, setPage] = useState<ReservationsPage | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    api.kpis().then(setKpis).catch((e) => toast.error(`KPIs: ${e.message}`));
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    api
      .reservations({ ...filters, limit: LIMIT, offset })
      .then(setPage)
      .catch((e) => toast.error(`Reservations: ${e.message}`))
      .finally(() => setLoading(false));
  }, [filters, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const onFilterChange = (next: Filters) => {
    setOffset(0);
    setFilters(next);
  };

  return (
    <div className="min-h-full">
      <Header />
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
        <KpiCards kpis={kpis} />
        <FilterBar filters={filters} onChange={onFilterChange} />
        <ReservationsTable
          items={page?.items ?? []}
          loading={loading}
          total={page?.total ?? 0}
          limit={LIMIT}
          offset={offset}
          onSelect={setSelectedId}
          onPage={setOffset}
        />
      </main>
    </div>
  );
}
