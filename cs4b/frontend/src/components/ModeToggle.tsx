import { Lock, Radio, RotateCcw } from "lucide-react";
import type { Health, Mode } from "../types";

/** Replay / Live switch. Live is disabled (with the server's reason) when /health says so. */
export default function ModeToggle({
  mode,
  health,
  offline,
  disabled,
  onChange,
}: {
  mode: Mode;
  health: Health | null;
  offline: boolean;
  disabled: boolean;
  onChange: (m: Mode) => void;
}) {
  if (offline)
    return (
      <span className="badge bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/30">
        <span className="h-1.5 w-1.5 rounded-full bg-rose-500" /> API offline
      </span>
    );

  const liveOk = !!health?.modes.live.available;
  const liveWhy = health ? (health.modes.live.reason ?? "Live mode is unavailable.") : "Checking…";
  const opt = (m: Mode, label: string, Icon: typeof Radio, enabled: boolean, tip: string) => {
    const active = mode === m;
    const tone =
      m === "live"
        ? "bg-amber-500 text-white shadow-sm dark:bg-amber-500"
        : "bg-white text-emerald-700 shadow-sm dark:bg-slate-900 dark:text-emerald-300";
    return (
      <span className="group relative">
        <button
          role="radio"
          aria-checked={active}
          aria-label={`${label} mode${enabled ? "" : ` (unavailable: ${tip})`}`}
          disabled={!enabled || disabled}
          onClick={() => !active && onChange(m)}
          className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold transition ${
            active ? tone : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
          } disabled:cursor-not-allowed ${!enabled ? "opacity-50" : ""}`}
        >
          {!enabled ? <Lock className="h-3 w-3" /> : <Icon className="h-3 w-3" />}
          {label}
        </button>
        {/* tooltip: shown on hover even when the button is disabled */}
        <span
          role="tooltip"
          className="pointer-events-none absolute left-1/2 top-full z-50 mt-2 w-64 -translate-x-1/2 rounded-lg bg-slate-900 px-3 py-2 text-[11px] font-normal leading-snug text-white opacity-0 shadow-lg transition group-hover:opacity-100 dark:bg-slate-700"
        >
          {tip}
        </span>
      </span>
    );
  };

  return (
    <div role="radiogroup" aria-label="Model mode" className="flex items-center gap-0.5 rounded-lg bg-slate-100 p-0.5 ring-1 ring-inset ring-slate-200 dark:bg-slate-800 dark:ring-slate-700">
      {opt("replay", "Replay", RotateCcw, true, "Replay: answers only from the recorded cache. Free, no key needed.")}
      {opt(
        "live",
        "Live",
        Radio,
        liveOk,
        liveOk ? "Live: new questions call Gemini (recorded ones still replay for free). Switching starts a new conversation." : liveWhy,
      )}
    </div>
  );
}
