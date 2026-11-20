import { useState } from "react";
import { Ban, ChevronDown, Coins, Cpu, Hash, ListOrdered, Radio, RotateCcw, Rows3, Sparkles, Wrench } from "lucide-react";
import type { AskResponse } from "../types";
import ResultTable from "./ResultTable";
import SqlBlock from "./SqlBlock";
import TraceTimeline from "./TraceTimeline";

function Badge({ icon: Icon, label, tone = "slate", title }: { icon: typeof Cpu; label: string; tone?: "slate" | "indigo" | "emerald" | "amber" | "rose"; title?: string }) {
  const tones = {
    slate: "bg-slate-50 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700",
    indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-500/30",
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30",
    amber: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30",
    rose: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/30",
  };
  return (
    <span className={`badge ${tones[tone]}`} title={title}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

export default function AnswerCard({ a }: { a: AskResponse }) {
  const repaired = a.attempts > 0;
  const failed = !a.declined && (a.error || a.stop) && !a.sql;
  const [open, setOpen] = useState(repaired);
  const [head, ...rest] = a.answer.split("\n");

  return (
    <div className={`card overflow-hidden ${a.declined ? "border-amber-300 dark:border-amber-500/40" : ""}`}>
      {a.declined ? (
        <div className="flex gap-3 border-b border-amber-200 bg-amber-50 px-5 py-4 dark:border-amber-500/30 dark:bg-amber-500/10">
          <Ban className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
          <div>
            <div className="text-sm font-semibold text-amber-900 dark:text-amber-200">Declined: the panel can't answer this</div>
            <p className="mt-1 text-sm text-amber-900/90 dark:text-amber-100/90">{a.decline_reason ?? a.answer}</p>
            <p className="mt-2 text-xs text-amber-700 dark:text-amber-300/80">No SQL was written, so nothing ran against the data.</p>
          </div>
        </div>
      ) : (
        <div className="px-5 pt-4">
          <div className={`text-base font-semibold ${failed ? "text-rose-700 dark:text-rose-300" : ""}`}>{head}</div>
          {rest.length > 0 && (
            <pre className="scroll-thin mt-2 overflow-x-auto whitespace-pre rounded-md bg-slate-50 px-3 py-2 font-mono text-xs leading-relaxed text-slate-600 dark:bg-slate-950 dark:text-slate-400">
              {rest.join("\n")}
            </pre>
          )}
          {a.explanation && (
            <p className="mt-2 flex gap-1.5 text-sm text-slate-600 dark:text-slate-400">
              <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" />
              {a.explanation}
            </p>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2 px-5 pt-3">
        {a.mode === "live" ? (
          <Badge
            icon={Radio}
            tone="amber"
            label={a.fresh_model_calls > 0 ? "Live" : "Live · cached"}
            title={
              a.fresh_model_calls > 0
                ? `Live: ${a.fresh_model_calls} call(s) reached Gemini`
                : "Live mode, but this exact request was already recorded, so it replayed for free"
            }
          />
        ) : (
          <Badge icon={RotateCcw} tone="emerald" label="Replay" title="Replayed from outputs/cache: no model call was made" />
        )}
        <Badge icon={Coins} tone="indigo" label={`$${a.usd.toFixed(6)}`} title="Cost at list price (free tier: $0 actual)" />
        <Badge icon={Cpu} label={`${a.model_calls} model call${a.model_calls === 1 ? "" : "s"}`} />
        <Badge
          icon={Wrench}
          tone={repaired ? "amber" : "emerald"}
          label={repaired ? `${a.attempts} repair${a.attempts === 1 ? "" : "s"}` : "first try"}
          title="Failed attempts that went down the repair edge"
        />
        <Badge icon={Hash} label={`${a.tokens.toLocaleString()} tokens`} />
        {!a.declined && <Badge icon={Rows3} label={`${a.row_count} row${a.row_count === 1 ? "" : "s"}`} />}
        {a.stop && <Badge icon={Ban} tone="rose" label={a.stop} />}
        <Badge icon={ListOrdered} label={`turn ${a.turn}`} title={a.thread_id} />
      </div>

      <div className="space-y-3 px-5 py-4">
        {a.sql && <SqlBlock sql={a.sql} />}
        {a.columns.length > 0 && a.rows.length > 0 && <ResultTable columns={a.columns} rows={a.rows} truncated={a.truncated} />}
      </div>

      <div className="border-t border-slate-100 dark:border-slate-800">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center justify-between px-5 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
          aria-expanded={open}
        >
          <span className="flex items-center gap-2">
            Trace <span className="text-xs font-normal text-slate-400">{a.trace.length} steps{repaired ? " · includes a repair" : ""}</span>
          </span>
          <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        {open && (
          <div className="px-5 pb-4 pt-1">
            <TraceTimeline trace={a.trace} />
          </div>
        )}
      </div>
    </div>
  );
}
