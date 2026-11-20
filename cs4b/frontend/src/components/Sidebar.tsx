import { MessageSquarePlus, PlayCircle } from "lucide-react";
import type { RecordedQuestion } from "../types";

const CATEGORY: Record<string, string> = {
  lookup: "bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-500/30",
  aggregation: "bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-500/30",
  cross_bdc: "bg-teal-50 text-teal-700 ring-teal-200 dark:bg-teal-500/10 dark:text-teal-300 dark:ring-teal-500/30",
  over_time: "bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200 dark:bg-fuchsia-500/10 dark:text-fuchsia-300 dark:ring-fuchsia-500/30",
  follow_up: "bg-indigo-50 text-indigo-700 ring-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-300 dark:ring-indigo-500/30",
  decline: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30",
};

export default function Sidebar({
  questions,
  busy,
  highlight,
  threadId,
  turns,
  onAsk,
  onNew,
  onDemo,
}: {
  questions: RecordedQuestion[];
  busy: boolean;
  highlight: boolean;
  threadId: string | null;
  turns: number;
  onAsk: (q: RecordedQuestion) => void;
  onNew: () => void;
  onDemo: () => void;
}) {
  return (
    <aside className="flex h-full w-full flex-col gap-4 overflow-hidden">
      <div className="space-y-2">
        <button className="btn-primary w-full" onClick={onNew} disabled={busy}>
          <MessageSquarePlus className="h-4 w-4" /> New conversation
        </button>
        <button className="btn-outline w-full" onClick={onDemo} disabled={busy} title="New conversation, then q02 and its follow-up q03 on the same thread">
          <PlayCircle className="h-4 w-4 text-indigo-500" /> Demo follow-up (q02 → q03)
        </button>
        <div className="px-1 text-xs text-slate-500 dark:text-slate-400">
          {threadId ? (
            <>
              Thread <span className="font-mono">{threadId}</span> · {turns} turn{turns === 1 ? "" : "s"}
            </>
          ) : (
            "No conversation yet: your first question starts one."
          )}
        </div>
      </div>

      <div className={`flex min-h-0 flex-1 flex-col rounded-xl border p-2 transition ${highlight ? "attention border-indigo-400 bg-indigo-50/60 dark:border-indigo-500/60 dark:bg-indigo-500/10" : "border-transparent"}`}>
        <div className="px-2 pb-2 pt-1">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Recorded questions</h2>
          <p className={`mt-0.5 text-xs ${highlight ? "font-medium text-indigo-700 dark:text-indigo-300" : "text-slate-400"}`}>
            {highlight ? "These are in the replay cache: pick one." : "Replay from the cache. Click to ask."}
          </p>
        </div>
        <ul className="scroll-thin -mr-1 flex-1 space-y-1 overflow-y-auto pr-1">
          {questions.map((q) => (
            <li key={q.id}>
              <button
                disabled={busy}
                onClick={() => onAsk(q)}
                className="group w-full rounded-lg px-2 py-2 text-left text-sm transition hover:bg-white hover:shadow-sm disabled:opacity-50 dark:hover:bg-slate-800"
              >
                <div className="mb-1 flex items-center gap-1.5">
                  <span className="font-mono text-[11px] text-slate-400">{q.id}</span>
                  <span className={`badge px-1.5 py-0 text-[10px] ${CATEGORY[q.category] ?? CATEGORY.lookup}`}>{q.category.replace("_", " ")}</span>
                  {q.follows && <span className="text-[10px] text-slate-400">after {q.follows}, same thread</span>}
                </div>
                <div className="leading-snug text-slate-700 group-hover:text-slate-900 dark:text-slate-300 dark:group-hover:text-white">{q.question}</div>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
