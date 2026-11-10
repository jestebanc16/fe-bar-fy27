import { Moon, Sun, TrendingUp } from "lucide-react";
import { useUI } from "../store";

export default function Header() {
  const theme = useUI((s) => s.theme);
  const toggleTheme = useUI((s) => s.toggleTheme);
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-6 w-6 text-indigo-600 dark:text-indigo-400" />
          <div>
            <h1 className="text-base font-semibold sm:text-lg">Meridian Hotels &amp; Resorts</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Revenue Manager · At-risk reservations &amp; actions
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label="Toggle theme"
          className="rounded-lg border border-slate-200 p-2 text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </button>
      </div>
    </header>
  );
}
