import { useEffect, useState } from "react";
import { ChevronRight, Table2, X } from "lucide-react";
import { api } from "../api";
import type { Economics, SchemaTable } from "../types";

export default function SchemaPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<"schema" | "economics">("schema");
  const [tables, setTables] = useState<SchemaTable[] | null>(null);
  const [econ, setEcon] = useState<Economics | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({ holdings_v: true });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.schema().then(setTables).catch((e) => setErr(e.message));
    api.economics().then(setEcon).catch(() => undefined);
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <div className="flex gap-1 rounded-lg bg-slate-100 p-0.5 text-sm dark:bg-slate-800">
          {(["schema", "economics"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-1 font-medium capitalize ${tab === t ? "bg-white shadow-sm dark:bg-slate-900" : "text-slate-500 dark:text-slate-400"}`}
            >
              {t}
            </button>
          ))}
        </div>
        <button className="btn-ghost p-1.5" onClick={onClose} aria-label="Close panel">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="scroll-thin flex-1 overflow-y-auto p-4">
        {tab === "schema" && (
          <>
            <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
              Read live over MCP (<span className="font-mono">list_tables</span>, <span className="font-mono">describe_table</span>). This is the same text the model reads.
            </p>
            {err && <p className="text-sm text-rose-600">{err}</p>}
            {!tables && !err && <p className="text-sm text-slate-400">Loading…</p>}
            <div className="space-y-2">
              {tables?.map((t) => (
                <div key={t.table} className="rounded-lg border border-slate-200 dark:border-slate-800">
                  <button
                    onClick={() => setOpen((o) => ({ ...o, [t.table]: !o[t.table] }))}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-semibold"
                  >
                    <ChevronRight className={`h-4 w-4 transition-transform ${open[t.table] ? "rotate-90" : ""}`} />
                    <Table2 className="h-4 w-4 text-indigo-500" />
                    <span className="font-mono">{t.table}</span>
                    <span className="ml-auto text-xs font-normal text-slate-400">{t.columns.length} columns</span>
                  </button>
                  {open[t.table] && (
                    <dl className="divide-y divide-slate-100 border-t border-slate-100 dark:divide-slate-800 dark:border-slate-800">
                      {t.columns.map((c) => (
                        <div key={c.column} className="px-3 py-1.5">
                          <dt className="font-mono text-xs font-medium text-slate-800 dark:text-slate-200">{c.column}</dt>
                          {c.description && <dd className="text-xs text-slate-500 dark:text-slate-400">{c.description}</dd>}
                        </div>
                      ))}
                    </dl>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {tab === "economics" && (
          <>
            {!econ && <p className="text-sm text-slate-400">Loading…</p>}
            {econ && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-2">
                  {[
                    ["Per question", `$${econ.computed.usd_per_question.toFixed(6)}`],
                    ["Ten questions", `$${econ.computed.usd_total.toFixed(6)}`],
                    ["Model calls / q", econ.computed.model_calls_per_question.toFixed(1)],
                    ["Repaired", String(econ.computed.repaired)],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                      <div className="text-[11px] uppercase tracking-wide text-slate-500">{k}</div>
                      <div className="mt-0.5 font-mono text-lg font-semibold">{v}</div>
                    </div>
                  ))}
                </div>
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Analyst time saved (10 questions)</div>
                  <div className="flex gap-2">
                    {econ.computed.hours_saved.map((h) => (
                      <div key={h.scenario} className="flex-1 rounded-lg bg-slate-50 p-2 text-center dark:bg-slate-800/60">
                        <div className="text-[11px] text-slate-500">{h.scenario}</div>
                        <div className="font-mono text-sm font-semibold">{h.hours.toFixed(2)} h</div>
                        <div className="font-mono text-xs text-slate-500">${Math.round(h.usd)}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="space-y-3">
                  {econ.lines.map((l) => (
                    <div key={l.line}>
                      <div className="text-xs font-semibold text-slate-700 dark:text-slate-200">{l.line}</div>
                      <p className="text-xs leading-relaxed text-slate-500 dark:text-slate-400">{l.value}</p>
                    </div>
                  ))}
                  <p className="text-[11px] text-slate-400">From {econ.source}</p>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
