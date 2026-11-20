// Mirrors cs4b/api/schemas.py

export type Mode = "replay" | "live";

export interface ModeStatus {
  available: boolean;
  reason: string | null;
}

export interface Health {
  status: "ok";
  default_mode: Mode;
  modes: Record<Mode, ModeStatus>;
  model: string;
  mcp_server: string;
  tools: string[];
  cached_responses: number;
  recorded_questions: number;
}

export interface RecordedQuestion {
  id: string;
  category: string;
  question: string;
  follows: string | null;
}

export interface TraceStep {
  step: number;
  node: string;
  ts: string;
  outcome?: string | null;
  attempt?: number | null;
  [extra: string]: unknown;
}

export type Cell = string | number | boolean | null;

export interface AskResponse {
  thread_id: string;
  mode: Mode;
  thread_reset: boolean;
  previous_thread_id: string | null;
  turn: number;
  question: string;
  answer: string;
  declined: boolean;
  decline_reason: string | null;
  explanation: string | null;
  sql: string | null;
  columns: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  usd: number;
  tokens: number;
  model_calls: number;
  fresh_model_calls: number;
  attempts: number;
  stop: string | null;
  error: { code?: string; detail?: string } | null;
  trace: TraceStep[];
}

export interface SchemaColumn {
  column: string;
  description: string;
}
export interface SchemaTable {
  table: string;
  columns: SchemaColumn[];
}

export interface Economics {
  source: string;
  lines: { line: string; value: string }[];
  computed: {
    questions: number;
    usd_total: number;
    usd_per_question: number;
    model_calls_per_question: number;
    repaired: number;
    no_sql: number;
    tokens_total: number;
    analyst_minutes_per_question: number;
    analyst_rate_usd: number;
    hours_saved: { scenario: string; hours: number; usd: number }[];
  };
}

export type Message =
  | { id: string; role: "user"; text: string; qid?: string }
  | { id: string; role: "assistant"; data: AskResponse }
  | { id: string; role: "pending"; text: string }
  | { id: string; role: "notice"; text: string }
  | { id: string; role: "error"; code: string; text: string; question: string };
