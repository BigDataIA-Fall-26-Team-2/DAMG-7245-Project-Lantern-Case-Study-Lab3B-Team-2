import { useMemo, useState } from "react";
import hljs from "highlight.js/lib/core";
import sql from "highlight.js/lib/languages/sql";
import { Check, Copy } from "lucide-react";

hljs.registerLanguage("sql", sql);

const BREAK_BEFORE =
  /\s+(?=\b(?:FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|LEFT JOIN|INNER JOIN|JOIN|UNION(?: ALL)?)\b)/gi;

/** Line breaks before the main clauses, outside string literals. Display only. */
export function prettySql(s: string): string {
  return s
    .split(/('(?:[^']|'')*')/)
    .map((part, i) => (i % 2 ? part : part.replace(BREAK_BEFORE, "\n")))
    .join("");
}

export default function SqlBlock({ sql: text }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  const html = useMemo(() => hljs.highlight(prettySql(text), { language: "sql" }).value, [text]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="group relative overflow-hidden rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950">
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <span>SQL</span>
        <button
          onClick={copy}
          className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-medium normal-case tracking-normal text-slate-600 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800"
          aria-label="Copy SQL"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="scroll-thin overflow-x-auto px-4 py-3 text-[13px] leading-relaxed">
        <code className="hljs font-mono" dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </div>
  );
}
