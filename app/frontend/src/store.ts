import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark";

interface UIState {
  theme: Theme;
  selectedId: string | null;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  setSelectedId: (id: string | null) => void;
}

const prefersDark =
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-color-scheme: dark)").matches;

export const useUI = create<UIState>()(
  persist(
    (set, get) => ({
      theme: prefersDark ? "dark" : "light",
      selectedId: null,
      setTheme: (t) => set({ theme: t }),
      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),
      setSelectedId: (id) => set({ selectedId: id }),
    }),
    { name: "hotel-app-ui", partialize: (s) => ({ theme: s.theme }) },
  ),
);
