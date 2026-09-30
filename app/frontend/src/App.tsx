import { useEffect } from "react";
import Header from "./components/Header";
import { useUI } from "./store";

export default function App() {
  const theme = useUI((s) => s.theme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <div className="min-h-full">
      <Header />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Loading dashboard…
        </p>
      </main>
    </div>
  );
}
