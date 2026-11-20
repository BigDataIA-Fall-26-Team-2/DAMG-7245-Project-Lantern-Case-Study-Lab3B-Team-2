import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import type { Cell } from "../types";

type Dir = "asc" | "desc";

const MONEY = /(fair_value|cost|principal|value|usd|amount)/i;
const RATE = /(rate|share|pct|percent|spread)/i;

function fmt(v: Cell, col: string): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (RATE.test(col) && Math.abs(v) < 1 && !/percent/i.test(col)) return `${(v * 100).toFixed(2)}%`;
    if (/percent|percentage/i.test(col)) return `${v.toFixed(2)}%`;
    if (MONEY.test(col) && Math.abs(v) >= 1000)
      return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
    return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(v);
}

function compare(a: Cell, b: Cell): number {
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1; // nulls last
  if (b === null || b === undefined) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export default function ResultTable({
  columns,
  rows,
  truncated,
}: {
  columns: string[];
  rows: Cell[][];
  truncated: boolean;
}) {
  const [sort, setSort] = useState<{ col: number; dir: Dir } | null>(null);

  const numeric = useMemo(
    () => columns.map((_, i) => rows.some((r) => typeof r[i] === "number") && rows.every((r) => r[i] === null || typeof r[i] === "number")),
    [columns, rows],
  );

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const out = [...rows].sort((a, b) => compare(a[sort.col], b[sort.col]));
    if (sort.dir === "desc") {
      // keep nulls last when descending too
      const nn = out.filter((r) => r[sort.col] !== null).reverse();
      return [...nn, ...out.filter((r) => r[sort.col] === null)];
    }
    return out;
  }, [rows, sort]);

  // click cycle per column: first direction (desc for numbers, asc for text) -> the other -> unsorted
  const toggle = (i: number) =>
    setSort((s) => {
      const first: Dir = numeric[i] ? "desc" : "asc";
      if (!s || s.col !== i) return { col: i, dir: first };
      if (s.dir === first) return { col: i, dir: first === "asc" ? "desc" : "asc" };
      return null;
    });

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
      <div className="scroll-thin max-h-[420px] overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-slate-100/95 backdrop-blur dark:bg-slate-800/95">
            <tr>
              <th className="w-10 px-3 py-2 text-right text-xs font-medium text-slate-400">#</th>
              {columns.map((c, i) => {
                const active = sort?.col === i;
                const Icon = !active ? ArrowUpDown : sort!.dir === "asc" ? ArrowUp : ArrowDown;
                return (
                  <th key={`${c}-${i}`} className={`px-3 py-2 font-semibold ${numeric[i] ? "text-right" : "text-left"}`}>
                    <button
                      onClick={() => toggle(i)}
                      className={`inline-flex items-center gap-1 whitespace-nowrap text-xs uppercase tracking-wide hover:text-indigo-600 dark:hover:text-indigo-300 ${active ? "text-indigo-600 dark:text-indigo-300" : "text-slate-600 dark:text-slate-300"}`}
                      title="Sort"
                    >
                      {c}
                      <Icon className={`h-3.5 w-3.5 ${active ? "" : "opacity-40"}`} />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, ri) => (
              <tr key={ri} className="border-t border-slate-100 odd:bg-white even:bg-slate-50/60 hover:bg-indigo-50/60 dark:border-slate-800 dark:odd:bg-slate-900 dark:even:bg-slate-900/40 dark:hover:bg-indigo-500/10">
                <td className="px-3 py-1.5 text-right font-mono text-xs text-slate-400">{ri + 1}</td>
                {r.map((v, ci) => (
                  <td
                    key={ci}
                    title={v === null ? "NULL" : String(v)}
                    className={`px-3 py-1.5 ${numeric[ci] ? "text-right font-mono tabular-nums" : "text-left"} ${v === null ? "text-slate-400" : ""} ${typeof v === "number" && v < 0 ? "text-rose-600 dark:text-rose-400" : ""}`}
                  >
                    {fmt(v, columns[ci])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {truncated && (
        <div className="border-t border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          Truncated at the server's 200-row cap.
        </div>
      )}
    </div>
  );
}
