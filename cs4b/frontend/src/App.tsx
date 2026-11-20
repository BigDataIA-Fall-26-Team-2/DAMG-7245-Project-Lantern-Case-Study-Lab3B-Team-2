import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Database, Info, Loader2, Menu, Moon, PanelRight, SendHorizontal, Sun, User, X } from "lucide-react";
import { ApiError, api } from "./api";
import AnswerCard from "./components/AnswerCard";
import ModeToggle from "./components/ModeToggle";
import SchemaPanel from "./components/SchemaPanel";
import Sidebar from "./components/Sidebar";
import type { Health, Message, Mode, RecordedQuestion } from "./types";

const CACHE_MISS =
  "This question isn't in the replay cache. Try one of the recorded questions, or switch to live mode with a Gemini key.";

let seq = 0;
const nextId = () => `m${++seq}`;

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("theme", dark ? "dark" : "light");
    } catch {
      /* storage blocked */
    }
  }, [dark]);
  return [dark, () => setDark((d) => !d)] as const;
}

export default function App() {
  const [dark, toggleTheme] = useTheme();
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [questions, setQuestions] = useState<RecordedQuestion[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const threadRef = useRef<string | null>(null);
  const [mode, setModeState] = useState<Mode>("replay");
  const modeRef = useRef<Mode>("replay");
  const [busy, setBusy] = useState(false);
  const [highlight, setHighlight] = useState(false);
  const [showSchema, setShowSchema] = useState(false);
  const [showSidebar, setShowSidebar] = useState(false);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const hlTimer = useRef<number>();

  const setThread = (t: string | null) => {
    threadRef.current = t;
    setThreadId(t);
  };

  const refreshHealth = useCallback(() => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        setOffline(false);
        // live disappeared (e.g. the API restarted without a key): fall back to replay
        if (modeRef.current === "live" && !h.modes.live.available) {
          modeRef.current = "replay";
          setModeState("replay");
        }
      })
      .catch(() => setOffline(true));
  }, []);

  useEffect(() => {
    refreshHealth();
    api.questions().then(setQuestions).catch(() => undefined);
  }, [refreshHealth]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const flagSidebar = () => {
    setHighlight(true);
    setShowSidebar(true);
    window.clearTimeout(hlTimer.current);
    hlTimer.current = window.setTimeout(() => setHighlight(false), 6000);
  };

  /** Ask on the current thread (or `tid`). Resolves true when an answer came back. */
  const ask = useCallback(async (text: string, qid?: string, tid?: string | null): Promise<boolean> => {
    const question = text.trim();
    if (!question) return false;
    const pendingId = nextId();
    setMessages((m) => [...m, { id: nextId(), role: "user", text: question, qid }, { id: pendingId, role: "pending", text: "Thinking…" }]);
    setBusy(true);
    try {
      const a = await api.ask(question, tid ?? threadRef.current, modeRef.current);
      setThread(a.thread_id);
      setMessages((m) =>
        m.flatMap((x): Message[] =>
          x.id !== pendingId
            ? [x]
            : [
                ...(a.thread_reset
                  ? [{ id: nextId(), role: "notice" as const, text: `That conversation was in the other mode, so a new ${a.mode === "live" ? "Live" : "Replay"} conversation started.` }]
                  : []),
                { id: pendingId, role: "assistant", data: a },
              ],
        ),
      );
      setOffline(false);
      return true;
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "unknown", String(e));
      if (err.code === "cache_miss") flagSidebar();
      if (err.code === "network") setOffline(true);
      if (err.code === "live_unavailable") refreshHealth();
      setMessages((m) =>
        m.map((x) =>
          x.id === pendingId ? { id: pendingId, role: "error", code: err.code, text: err.code === "cache_miss" ? CACHE_MISS : err.message, question } : x,
        ),
      );
      return false;
    } finally {
      setBusy(false);
    }
  }, [refreshHealth]);

  const newConversation = async (notice?: string) => {
    // drop the old thread at once, so nothing asked meanwhile can land on it
    setThread(null);
    setMessages(notice ? [{ id: nextId(), role: "notice", text: notice }] : []);
    setHighlight(false);
    setBusy(true);
    try {
      const tid = await api.newConversation(modeRef.current);
      if (threadRef.current === null) setThread(tid);
    } catch {
      /* the first /ask will start a thread */
    } finally {
      setBusy(false);
    }
  };

  /** Switching mode always starts a new conversation: threads never mix modes. */
  const switchMode = (m: Mode) => {
    if (m === modeRef.current) return;
    modeRef.current = m;
    setModeState(m);
    void newConversation(
      m === "live"
        ? "Live mode: new questions call Gemini (recorded ones still replay for free). This is a new conversation."
        : "Replay mode: answers come only from the recorded cache. This is a new conversation.",
    );
  };

  const demoFollowUp = async () => {
    const q2 = questions.find((q) => q.id === "q02");
    const q3 = questions.find((q) => q.id === "q03");
    if (!q2 || !q3) return;
    setShowSidebar(false);
    setThread(null);
    setMessages([]);
    let tid: string | null = null;
    try {
      tid = await api.newConversation(modeRef.current);
    } catch {
      /* ask() will report the error */
    }
    setThread(tid);
    if (await ask(q2.question, q2.id, tid)) await ask(q3.question, q3.id, threadRef.current);
  };

  const submit = () => {
    if (busy || !draft.trim()) return;
    const t = draft;
    setDraft("");
    void ask(t);
  };

  const turns = messages.filter((m) => m.role === "assistant").length;
  const spent = messages.reduce((s, m) => (m.role === "assistant" ? s + m.data.usd : s), 0);

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <header className="z-20 flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white/80 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
        <button className="btn-ghost p-1.5 lg:hidden" onClick={() => setShowSidebar((s) => !s)} aria-label="Questions">
          <Menu className="h-5 w-5" />
        </button>
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-sm">
            <Database className="h-4 w-4" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold">Ask the Panel</div>
            <div className="hidden text-[11px] text-slate-500 sm:block dark:text-slate-400">BDC holdings · 73 10-Q filings · read-only over MCP</div>
          </div>
        </div>
        <ModeToggle mode={mode} health={health} offline={offline} disabled={busy} onChange={switchMode} />
        {health && <span className="hidden font-mono text-[11px] text-slate-400 md:inline">{health.model}</span>}
        <div className="ml-auto flex items-center gap-1">
          {turns > 0 && (
            <span className="mr-2 hidden text-xs text-slate-500 sm:inline dark:text-slate-400">
              Conversation: <span className="font-mono">${spent.toFixed(6)}</span>
            </span>
          )}
          <button className={`btn-ghost ${showSchema ? "bg-slate-100 dark:bg-slate-800" : ""}`} onClick={() => setShowSchema((s) => !s)}>
            <PanelRight className="h-4 w-4" /> <span className="hidden sm:inline">Schema</span>
          </button>
          <button className="btn-ghost p-2" onClick={toggleTheme} aria-label="Toggle theme" title={dark ? "Light mode" : "Dark mode"}>
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1">
        {/* sidebar */}
        <div
          className={`absolute inset-y-0 left-0 z-30 w-80 border-r border-slate-200 bg-slate-50 p-4 transition-transform dark:border-slate-800 dark:bg-slate-950 lg:static lg:translate-x-0 ${showSidebar ? "translate-x-0 shadow-xl" : "-translate-x-full"}`}
        >
          <button className="btn-ghost absolute right-2 top-2 p-1 lg:hidden" onClick={() => setShowSidebar(false)} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
          <Sidebar
            questions={questions}
            busy={busy}
            highlight={highlight}
            threadId={threadId}
            turns={turns}
            onAsk={(q) => {
              setShowSidebar(false);
              setHighlight(false);
              void ask(q.question, q.id);
            }}
            onNew={() => void newConversation()}
            onDemo={demoFollowUp}
          />
        </div>

        {/* chat */}
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="scroll-thin flex-1 overflow-y-auto">
            <div className="mx-auto max-w-4xl space-y-5 px-4 py-6">
              {messages.every((m) => m.role === "notice") && (
                <div className="card mx-auto mt-10 max-w-xl p-8 text-center">
                  <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300">
                    <Database className="h-6 w-6" />
                  </div>
                  <h1 className="text-lg font-semibold">Ask a question about the BDC holdings panel</h1>
                  <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                    Each answer shows the SQL behind it, the rows, what it cost and every step the agent took. The agent reads through a read-only MCP server
                    and never writes.
                  </p>
                  <p className="mt-3 text-xs text-slate-400">
                    {mode === "live"
                      ? "Live mode: type any question. New ones call Gemini; recorded ones still replay for free."
                      : "Replay mode: pick a recorded question from the sidebar, or try the follow-up demo."}
                  </p>
                </div>
              )}
              {messages.map((m) => {
                if (m.role === "user")
                  return (
                    <div key={m.id} className="flex justify-end gap-2">
                      <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">
                        {m.qid && <span className="mr-2 rounded bg-white/20 px-1.5 py-0.5 font-mono text-[10px]">{m.qid}</span>}
                        {m.text}
                      </div>
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        <User className="h-4 w-4" />
                      </div>
                    </div>
                  );
                if (m.role === "notice")
                  return (
                    <div key={m.id} className="flex items-center justify-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                      <Info className="h-3.5 w-3.5" /> {m.text}
                    </div>
                  );
                if (m.role === "pending")
                  return (
                    <div key={m.id} className="flex items-center gap-2 text-sm text-slate-500">
                      <Loader2 className="h-4 w-4 animate-spin" /> {m.text}
                    </div>
                  );
                if (m.role === "error")
                  return (
                    <div
                      key={m.id}
                      className={`card flex gap-3 p-4 ${m.code === "cache_miss" ? "border-indigo-200 bg-indigo-50/50 dark:border-indigo-500/30 dark:bg-indigo-500/5" : "border-rose-200 bg-rose-50/50 dark:border-rose-500/30 dark:bg-rose-500/5"}`}
                    >
                      <AlertCircle className={`mt-0.5 h-5 w-5 shrink-0 ${m.code === "cache_miss" ? "text-indigo-500" : "text-rose-500"}`} />
                      <div className="text-sm">
                        <div className="font-medium">{m.text}</div>
                        {m.code === "cache_miss" && (
                          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                            Follow-ups replay only right after the question they follow, on the same conversation (q03 after q02).
                          </div>
                        )}
                      </div>
                    </div>
                  );
                return <AnswerCard key={m.id} a={m.data} />;
              })}
              <div ref={endRef} />
            </div>
          </div>

          {/* composer */}
          <div className="border-t border-slate-200 bg-white/80 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
            <form
              className="mx-auto flex max-w-4xl items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
                rows={1}
                placeholder={threadId && turns ? "Ask a follow-up on this conversation…" : "Ask about the BDC holdings…"}
                className="max-h-40 min-h-[42px] flex-1 resize-none rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm shadow-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 dark:border-slate-700 dark:bg-slate-950"
              />
              <button type="submit" className="btn-primary h-[42px] px-4" disabled={busy || !draft.trim()} aria-label="Send">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizontal className="h-4 w-4" />}
              </button>
            </form>
          </div>
        </main>

        {/* schema drawer */}
        {showSchema && (
          <div className="absolute inset-y-0 right-0 z-30 w-full max-w-sm border-l border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900 xl:static xl:shadow-none">
            <SchemaPanel onClose={() => setShowSchema(false)} />
          </div>
        )}
      </div>
    </div>
  );
}
