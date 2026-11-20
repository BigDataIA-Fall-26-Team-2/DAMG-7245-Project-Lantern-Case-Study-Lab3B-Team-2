import { AlertTriangle, Ban, CheckCircle2, CircleDot, Cpu, Database, FileText, RotateCcw, ShieldCheck } from "lucide-react";
import type { TraceStep } from "../types";

const ICON: Record<string, typeof Cpu> = {
  load_schema: FileText,
  generate: Cpu,
  check: ShieldCheck,
  execute: Database,
  summarize: CheckCircle2,
};

const LABEL: Record<string, string> = {
  load_schema: "Load schema (MCP list_tables, describe_table, sample_values)",
  generate: "Generate SQL (model)",
  check: "Check (Pydantic contract)",
  execute: "Execute (MCP run_query, server gate)",
  summarize: "Summarize",
};

const SKIP = new Set(["step", "node", "ts", "outcome", "attempt", "run_id"]);

function failed(t: TraceStep) {
  return !!t.outcome && t.outcome !== "ok" && t.outcome !== "decline";
}

function short(v: unknown): string {
  if (typeof v === "string" && /^[0-9a-f]{40,}$/.test(v)) return v.slice(0, 12);
  if (typeof v === "number") return v < 0.01 && v > 0 ? `$${v.toFixed(6)}` : String(v);
  return String(v);
}

export default function TraceTimeline({ trace }: { trace: TraceStep[] }) {
  return (
    <ol className="relative ml-2 border-l border-slate-200 dark:border-slate-700">
      {trace.map((t, i) => {
        const bad = failed(t);
        const retry = t.node === "generate" && (t.attempt ?? 0) > 0;
        const Icon = bad ? AlertTriangle : t.outcome === "decline" ? Ban : retry ? RotateCcw : ICON[t.node] ?? CircleDot;
        const extras = Object.entries(t).filter(([k, v]) => !SKIP.has(k) && v !== null && v !== undefined && v !== "");
        const tone = bad
          ? "bg-rose-100 text-rose-600 ring-rose-300 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-500/40"
          : retry
            ? "bg-amber-100 text-amber-700 ring-amber-300 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-500/40"
            : t.outcome === "decline"
              ? "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30"
              : "bg-white text-indigo-600 ring-slate-200 dark:bg-slate-900 dark:text-indigo-300 dark:ring-slate-700";
        return (
          <li key={i} className="mb-3 ml-5 last:mb-0">
            <span className={`absolute -left-[13px] mt-0.5 flex h-6 w-6 items-center justify-center rounded-full ring-1 ${tone}`}>
              <Icon className="h-3.5 w-3.5" />
            </span>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-mono text-xs text-slate-400">#{t.step}</span>
              <span className="font-medium">{LABEL[t.node] ?? t.node}</span>
              {retry && (
                <span className="badge bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30">
                  repair attempt {t.attempt}
                </span>
              )}
              {t.outcome && (
                <span
                  className={`badge ${
                    bad
                      ? "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/30"
                      : t.outcome === "decline"
                        ? "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30"
                        : "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30"
                  }`}
                >
                  {t.outcome}
                </span>
              )}
            </div>
            {bad && (
              <div className="mt-1 text-xs text-rose-600 dark:text-rose-300">
                {trace[i + 1]?.node === "generate"
                  ? "Refused: the error code goes back to the model for a repair."
                  : "Refused, and the repair limit was reached."}
              </div>
            )}
            {extras.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-slate-500 dark:text-slate-400">
                {extras.map(([k, v]) => (
                  <span key={k}>
                    {k}=<span className="text-slate-700 dark:text-slate-300">{short(v)}</span>
                  </span>
                ))}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
