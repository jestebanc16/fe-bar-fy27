import { useState } from "react";
import toast from "react-hot-toast";
import { api } from "../api";
import { ACTION_TYPES, type ActionType } from "../types";

const LABELS: Record<ActionType, string> = {
  reconfirmed: "Reconfirmed",
  deposit_requested: "Deposit requested",
  overbooked_backup: "Overbooking backup",
  released: "Released",
  note: "Note",
};

export default function ActionForm({
  reservationId,
  onCreated,
}: {
  reservationId: string;
  onCreated: () => void;
}) {
  const [actionType, setActionType] = useState<ActionType>("reconfirmed");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.createAction(reservationId, {
        action_type: actionType,
        note: note.trim() || undefined,
      });
      toast.success("Action recorded");
      setNote("");
      onCreated();
    } catch (err) {
      toast.error(`Failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900";

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">
        Action
        <select
          className={`mt-1 ${inputCls}`}
          value={actionType}
          onChange={(e) => setActionType(e.target.value as ActionType)}
        >
          {ACTION_TYPES.map((a) => (
            <option key={a} value={a}>
              {LABELS[a]}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">
        Note (optional)
        <textarea
          className={`mt-1 ${inputCls}`}
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Context for this action…"
        />
      </label>
      <button
        type="submit"
        disabled={saving}
        className="w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-50"
      >
        {saving ? "Recording…" : "Record action"}
      </button>
    </form>
  );
}
